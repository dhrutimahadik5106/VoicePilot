"""Single-effect launch control using Phase 5B transitions and private-field-free audit."""
from math import isfinite
from threading import Event, Lock
from time import monotonic
from app.execution.state import Machine, TRANSITIONS
from app.execution.models import State
from app.launch.models import (AdapterMetadata, Configuration, LaunchAudit, LaunchError,
                               LaunchPlan, LaunchResult, ProcessObservation, Status)
from app.launch.authorization import ManualAuthority, VoiceAuthority, plan_document
from app.launch.windows import WindowsBackend


class WindowsLaunchAdapter:
    """Phase 5B adapter protocol shape, specialized for a real, no-argument launch."""
    spec = AdapterMetadata()
    input_schema = LaunchPlan

    def __init__(self, backend, configuration, guard, clock=monotonic):
        self.backend, self.configuration, self.guard = backend, configuration, guard
        self.clock = clock
        self.plans = {}
        self.attempted = False

    def precondition(self, step):
        plan_document(step)
        return step.application_id in self.configuration.approved_application_ids

    def execute(self, key, step, cancel):
        if not self.precondition(step) or cancel.is_set():
            raise LaunchError(Status.CANCELLED)
        revalidation_start = self.clock()
        with self.backend.revalidate(step.application_id, step.identity, self.configuration.discovery_timeout) as image:
            self.guard()
            if self.clock() - revalidation_start >= self.configuration.discovery_timeout:
                raise LaunchError(Status.TIMED_OUT)
            launch_start = self.clock()
            self.attempted = True
            def launch_guard():
                self.guard()
                if self.clock() - launch_start >= self.configuration.launch_timeout:
                    raise LaunchError(Status.TIMED_OUT)
            self.backend.launch(image, guard=launch_guard)
            if self.clock() - launch_start >= self.configuration.launch_timeout:
                raise LaunchError(Status.TIMED_OUT)
        self.plans[key] = step
        return True

    def observe(self, key):
        step = self.plans[key]
        return self.backend.observe(step.application_id, step.identity, self.configuration.observation_timeout)

    def verify(self, step, before, after):
        return verify_observation(step, after)

    def rollback(self, key, before, cancel):
        return False  # Never close or kill applications.


def verify_observation(plan, observation):
    return (type(observation) is ProcessObservation and observation.available and observation.matched
            and observation.application_id == plan.application_id and observation.identity == plan.identity)


class LaunchController:
    def __init__(self, configuration=None, *, backend=None, clock=monotonic):
        config = configuration or Configuration()
        self.configuration = Configuration.model_validate(config.model_dump())
        self.backend = backend or WindowsBackend()
        self.clock = clock
        self.stop = Event()
        self._lock = Lock()
        self._active = None
        self._used = set()

    def emergency_stop(self):
        self.stop.set()
        if self._active is not None:
            self._active.set()

    def run(self, plan, permit, authority, *, cancel=None):
        if not self._lock.acquire(blocking=False):
            return LaunchResult(status=Status.INVALID_AUTHORIZATION, state=State.BLOCKED)
        from app.owner.authorization import LaunchAuthority
        permitted = False
        validated = False
        attempted = False
        observed = False
        backend_accessed = False
        adapter = None
        cancellation_context = None
        machine = Machine(event_factory=lambda **data: LaunchAudit(**data, execution_permitted=permitted))
        try:
            started = self.clock()
            if not isfinite(started):
                raise LaunchError(Status.TIMED_OUT)
            plan_document(plan)
            validated = True
            if type(authority) not in {ManualAuthority, VoiceAuthority, LaunchAuthority} or plan.mode != authority.mode:
                raise LaunchError(Status.INVALID_AUTHORIZATION)
            if (not self.configuration.windows_adapter_enabled
                    or plan.application_id not in self.configuration.approved_application_ids
                    or plan.mode == "manual_operator_test" and not self.configuration.manual_launch_testing_enabled
                    or plan.mode == "authenticated_voice" and not self.configuration.real_execution_enabled):
                raise LaunchError(Status.DISABLED)
            self._active = cancel if type(cancel) is Event else Event()
            if cancel is not None and type(cancel) is not Event:
                raise LaunchError(Status.CANCELLED)
            from app.execution.cancellation import GLOBAL
            cancellation_context = GLOBAL.track(self._active)
            cancellation_context.__enter__()
            machine.plan_id, machine.step_id, machine.capability = plan.plan_id, plan.step_id, "application.launch"
            machine.move(State.VALIDATING, Status.AVAILABLE)
            if self.stop.is_set() or self._active.is_set():
                raise LaunchError(Status.EMERGENCY_STOPPED if self.stop.is_set() else Status.CANCELLED)
            machine.move(State.AWAITING, Status.AVAILABLE)
            if type(authority) is LaunchAuthority:
                synthetic = getattr(authority, "synthetic", None)
                if type(synthetic) is not bool or (
                    synthetic and getattr(self.backend, "fake", False) is not True
                ):
                    raise LaunchError(Status.ACCESS_DENIED)
            expires = authority.consume(plan, permit)
            if not expires or plan.plan_id in self._used or len(self._used) >= 100:
                raise LaunchError(Status.INVALID_AUTHORIZATION)
            self._used.add(plan.plan_id)
            permitted = True
            machine.move(State.AUTHORIZED, Status.AVAILABLE)

            def guard():
                if type(authority) is LaunchAuthority:
                    synthetic = getattr(authority, "synthetic", None)
                    if type(synthetic) is not bool or (
                        synthetic and getattr(self.backend, "fake", False) is not True
                    ):
                        raise LaunchError(Status.ACCESS_DENIED)
                    authority.validate_live()
                if self.stop.is_set():
                    raise LaunchError(Status.EMERGENCY_STOPPED)
                if self._active.is_set():
                    raise LaunchError(Status.CANCELLED)
                elapsed = self.clock() - started
                if (not isfinite(elapsed) or elapsed < 0 or elapsed >= total_timeout
                        or authority.clock() >= expires):
                    raise LaunchError(Status.TIMED_OUT)

            total_timeout = (self.configuration.discovery_timeout + self.configuration.launch_timeout
                             + 2 * self.configuration.observation_timeout)
            guard()
            # Independent OS observation is separate from adapter return values.
            initial_start = self.clock()
            backend_accessed = True
            before = self.backend.observe(plan.application_id, plan.identity, self.configuration.observation_timeout)
            guard()
            if self.clock() - initial_start >= self.configuration.observation_timeout:
                raise LaunchError(Status.TIMED_OUT)
            if (type(before) is not ProcessObservation or not before.available
                    or before.application_id != plan.application_id or before.identity != plan.identity):
                raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
            already = plan.application_id != "notepad" and verify_observation(plan, before)
            machine.move(State.RUNNING, Status.AVAILABLE)
            if not already:
                adapter = WindowsLaunchAdapter(self.backend, self.configuration, guard, self.clock)
                launch_start = self.clock()
                adapter.execute((plan.plan_id, plan.step_id), plan, self._active)
                attempted = adapter.attempted
                guard()
                if self.clock() - launch_start >= self.configuration.launch_timeout + self.configuration.discovery_timeout:
                    raise LaunchError(Status.TIMED_OUT)
            machine.move(State.OBSERVING, Status.AVAILABLE)
            after = before if already else None
            end = self.clock() + self.configuration.observation_timeout
            for _ in range(301):
                guard()
                if verify_observation(plan, after):
                    observed = True
                    break
                if self.clock() >= end:
                    break
                after = self.backend.observe(plan.application_id, plan.identity, max(.001, end - self.clock()))
                guard()
                if self.clock() >= end:
                    if verify_observation(plan, after):
                        raise LaunchError(Status.TIMED_OUT)
                    break
                if type(after) is not ProcessObservation or not after.available:
                    raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                if verify_observation(plan, after):
                    observed = True
                    break
                self._active.wait(min(.1, max(0, end - self.clock())))
            machine.move(State.VERIFYING, Status.AVAILABLE)
            if not observed:
                raise LaunchError(Status.VERIFICATION_FAILED)
            guard()
            status = Status.ALREADY_RUNNING if already else Status.LAUNCHED
            machine.move(State.SUCCEEDED, status, self.clock() - started)
            return LaunchResult(status=status, state=machine.state, application_id=plan.application_id,
                                mode=plan.mode, process_creation_attempted=attempted, process_observed=True,
                                execution_permitted=True, events=tuple(machine.events))
        except (Exception, KeyboardInterrupt) as error:
            status = (Status.CANCELLED if isinstance(error, KeyboardInterrupt)
                      else error.status if isinstance(error, LaunchError) else Status.LAUNCH_FAILED)
            attempted = attempted or bool(adapter and adapter.attempted)
            allowed = TRANSITIONS.get(machine.state, frozenset())
            preferred = (State.CANCELLED if status in {Status.CANCELLED, Status.EMERGENCY_STOPPED}
                         else State.TIMED_OUT if status == Status.TIMED_OUT else State.BLOCKED)
            target = next((s for s in (preferred, State.FAILED, State.UNVERIFIED, State.BLOCKED) if s in allowed), State.BLOCKED)
            if target in allowed:
                machine.move(target, status)
            return LaunchResult(status=status, state=target,
                                application_id=plan.application_id if validated else None,
                                mode=plan.mode if validated else "manual_operator_test",
                                process_creation_attempted=attempted, process_observed=False,
                                execution_permitted=permitted, events=tuple(machine.events))
        finally:
            if backend_accessed and plan.application_id == "notepad":
                try:
                    cleanup = getattr(self.backend, "finish_notepad", None)
                    if cleanup is not None:
                        cleanup()
                except Exception:
                    pass  # Handle cleanup cannot create a success or expose native errors.
            if cancellation_context is not None:
                cancellation_context.__exit__(None, None, None)
            self._active = None
            self._lock.release()
