"""Closed one-action driver using Phase 5B transitions and independent reads."""
from collections import deque
from math import isfinite
from threading import Event as Signal, Lock
from time import monotonic
from app.execution.cancellation import GLOBAL
from app.execution.state import Machine, TRANSITIONS
from app.execution.models import State
from app.operations.models import (Capability as C, Code, Configuration, Event, Result,
    OperationError, Transition, Volume, Brightness, validate_plan)
from app.operations.registry import REGISTRY, READS, SAFETY
from app.operations.authorization import ManualAuthority
from app.operations.adapters import StateAdapter, ScreenshotAdapter


def volume_matches(before, after, percent, muted, tolerance):
    return (type(after) is Volume and after.endpoint == before.endpoint
            and abs(after.percent - percent) <= tolerance and after.muted is muted)


class Controller:
    def __init__(self, configuration=None, *, backend=None, store=None, hub=None, clock=monotonic):
        config = configuration or Configuration()
        self.configuration = Configuration.model_validate(config.model_dump())
        if backend is None:
            from app.operations.windows import WindowsBackend
            backend = WindowsBackend()
        self.backend, self.store = backend, store
        self.hub, self.clock = hub or GLOBAL, clock
        self.history = deque(maxlen=config.history_limit)
        self.history_lock = Lock()
        self.lock = Lock()
        self.used = set()
        self.previous = None  # Private process-local recovery evidence, never history.

    def history_snapshot(self):
        with self.history_lock:
            return tuple(self.history)

    def _record(self, plan, result, started):
        elapsed = self.clock() - started
        duration = min(3600, max(0, elapsed)) if isfinite(elapsed) else 0
        with self.history_lock:
            self.history.append(Event(action_id=plan.action_id, capability=plan.capability,
                code=result.code, duration=duration, fake=result.fake,
                confirmation_required=REGISTRY[plan.capability].mutation,
                execution_permitted=result.execution_permitted))
        return result

    def run(self, plan, permit=None, authority=None, *, cancel=None):
        from app.owner.authorization import OperationAuthority
        started = self.clock()
        try:
            plan = validate_plan(plan)
        except Exception:
            return Result(code=Code.INVALID)
        cap = plan.capability
        fake = getattr(self.backend, "fake", False) is True
        if cap in SAFETY:
            count = self.hub.cancel(emergency=cap == C.STOP)
            result = Result(action_id=plan.action_id, code=Code.CANCEL_REQUESTED if count else Code.NOTHING_ACTIVE,
                            fake=fake)
            return self._record(plan, result, started)
        if cap == C.HISTORY:
            return self._record(plan, Result(action_id=plan.action_id, code=Code.READ, verified=True, fake=fake), started)
        if not self.lock.acquire(blocking=False):
            return Result(code=Code.DENIED, fake=fake)
        machine = Machine(event_factory=Transition)
        machine.plan_id, machine.step_id, machine.capability = plan.action_id, plan.step_id, cap
        allowed = False
        attempted = False
        before = None
        deadline = None
        active = cancel if type(cancel) is Signal else Signal()
        mutation = REGISTRY[cap].mutation
        result_fields = {}
        recovery = "not_needed"
        self.previous = None
        try:
            if cancel is not None and type(cancel) is not Signal:
                raise OperationError(Code.INVALID)
            def guard():
                if type(authority) is OperationAuthority:
                    synthetic = getattr(authority, "synthetic", None)
                    if type(synthetic) is not bool or (
                        synthetic and getattr(self.backend, "fake", False) is not True
                    ):
                        raise OperationError(Code.DENIED)
                    authority.validate_live()
                elapsed = self.clock() - started
                if self.hub.stopped.is_set():
                    raise OperationError(Code.STOPPED)
                if active.is_set():
                    raise OperationError(Code.CANCELLED)
                if not isfinite(elapsed) or elapsed < 0 or elapsed >= self.configuration.operation_timeout:
                    raise OperationError(Code.TIMEOUT)
                if deadline is not None and authority.clock() >= deadline:
                    raise OperationError(Code.EXPIRED)

            def observe(fn):
                guard()
                begin = self.clock()
                value = fn()
                guard()
                if self.clock() - begin >= self.configuration.observation_timeout:
                    raise OperationError(Code.TIMEOUT)
                return value

            with self.hub.track(active):
                machine.move(State.VALIDATING, Code.READ)
                guard()
                if mutation and (not self.configuration.enabled or
                                 type(authority) is not OperationAuthority and not self.configuration.manual_testing_enabled):
                    raise OperationError(Code.DENIED)
                if cap == C.SCREENSHOT and not self.configuration.screenshot_enabled:
                    raise OperationError(Code.DENIED)
                machine.move(State.AWAITING, Code.CONFIRMATION)
                if mutation or type(authority) is OperationAuthority:
                    if type(authority) not in {ManualAuthority, OperationAuthority}:
                        raise OperationError(Code.CONFIRMATION)
                    deadline = authority.consume(plan, permit)
                    if plan.action_id in self.used or len(self.used) >= 1000:
                        raise OperationError(Code.REPLAYED)
                    self.used.add(plan.action_id)
                    allowed = True
                machine.move(State.AUTHORIZED, Code.READ)
                guard()
                machine.move(State.RUNNING, Code.READ)
                if cap.value.startswith("system.volume."):
                    before = observe(self.backend.read_volume)
                    if type(before) is not Volume:
                        raise OperationError(Code.NO_OBSERVATION)
                    self.previous = before
                    percent, muted = before.percent, before.muted
                    if cap == C.VOLUME_SET:
                        percent = plan.percentage
                    elif cap == C.VOLUME_UP:
                        percent = min(100, before.percent + self.configuration.volume_step)
                    elif cap == C.VOLUME_DOWN:
                        percent = max(0, before.percent - self.configuration.volume_step)
                    elif cap in {C.MUTE, C.UNMUTE}:
                        muted = cap == C.MUTE
                    changed = not volume_matches(before, before, percent, muted, self.configuration.volume_tolerance)
                    if mutation and changed:
                        guard()
                        attempted = True
                        adapter = StateAdapter(cap, self.backend, before,
                            muted if cap in {C.MUTE, C.UNMUTE} else percent, guard)
                        adapter.execute((plan.action_id, plan.step_id), plan, active)
                    machine.move(State.OBSERVING, Code.READ)
                    after = observe(self.backend.read_volume)
                    machine.move(State.VERIFYING, Code.READ)
                    if not volume_matches(before, after, percent, muted, self.configuration.volume_tolerance):
                        recovery = ("previous_state_observed" if volume_matches(before, after,
                            before.percent, before.muted, self.configuration.volume_tolerance) else "not_restored")
                        raise OperationError(Code.UNVERIFIED)
                    result_fields["volume"] = after
                    code = Code.READ if not mutation else Code.CHANGED if changed else Code.ALREADY
                elif cap.value.startswith("system.brightness."):
                    before = observe(self.backend.read_brightness)
                    if type(before) is not Brightness:
                        raise OperationError(Code.NO_OBSERVATION)
                    if not before.supported or before.percent is None:
                        raise OperationError(Code.UNSUPPORTED)
                    self.previous = before
                    target = before.percent
                    if cap == C.BRIGHTNESS_SET:
                        target = plan.percentage
                    elif cap == C.BRIGHTNESS_UP:
                        target = min(100, target + self.configuration.brightness_step)
                    elif cap == C.BRIGHTNESS_DOWN:
                        target = max(0, target - self.configuration.brightness_step)
                    if mutation and not before.mutation_supported:
                        raise OperationError(Code.UNSUPPORTED)
                    if mutation and target != before.percent:
                        guard()
                        attempted = True
                        StateAdapter(cap, self.backend, before, target, guard).execute(
                            (plan.action_id, plan.step_id), plan, active)
                    machine.move(State.OBSERVING, Code.READ)
                    after = observe(self.backend.read_brightness)
                    machine.move(State.VERIFYING, Code.READ)
                    if (type(after) is not Brightness or not after.supported
                            or after.target != before.target or after.percent != target):
                        recovery = "unknown"
                        raise OperationError(Code.UNVERIFIED)
                    result_fields["brightness"] = after
                    code = Code.READ if not mutation else Code.ALREADY if target == before.percent else Code.CHANGED
                elif cap in {C.SCREENSHOT, C.SCREENSHOT_DELETE}:
                    if self.store is None:
                        from app.operations.screenshots import ScreenshotStore
                        self.store = ScreenshotStore()
                    guard()
                    attempted = True
                    adapter = ScreenshotAdapter(cap, self.backend, self.store, guard)
                    adapter.execute((plan.action_id, plan.step_id), plan, active)
                    key = adapter.artifact_id
                    result_fields["artifact_id"] = key
                    machine.move(State.OBSERVING, Code.READ)
                    if cap == C.SCREENSHOT:
                        dimensions = observe(lambda: self.store.verify(key))
                        if (type(dimensions) is not tuple or len(dimensions) != 2
                                or any(type(v) is not int or not 0 < v <= 16384 for v in dimensions)):
                            raise OperationError(Code.UNVERIFIED)
                    elif observe(lambda: self.store.exists(key)):
                        raise OperationError(Code.UNVERIFIED)
                    machine.move(State.VERIFYING, Code.READ)
                    result_fields["artifact_id"] = key
                    code = Code.CAPTURED if cap == C.SCREENSHOT else Code.DELETED
                else:
                    raise OperationError(Code.UNSUPPORTED)
                guard()
                machine.move(State.SUCCEEDED, code)
                result = Result(action_id=plan.action_id, code=code, verified=True, fake=fake,
                    execution_permitted=allowed, mutation_attempted=attempted,
                    transitions=tuple(machine.events), **result_fields)
        except (Exception, KeyboardInterrupt) as error:
            code = Code.CANCELLED if isinstance(error, KeyboardInterrupt) else error.code if isinstance(error, OperationError) else Code.FAILED
            if attempted and recovery == "not_needed":
                recovery = "unknown"  # No automatic rollback or false restoration claim.
            targets = TRANSITIONS.get(machine.state, ())
            desired = State.CANCELLED if code in {Code.CANCELLED, Code.STOPPED} else State.TIMED_OUT if code == Code.TIMEOUT else State.FAILED
            target = next((s for s in (desired, State.UNVERIFIED, State.BLOCKED) if s in targets), None)
            if target is not None:
                machine.move(target, code)
            result = Result(action_id=plan.action_id, code=code, fake=fake, execution_permitted=allowed,
                mutation_attempted=attempted, recovery=recovery, transitions=tuple(machine.events), **result_fields)
        finally:
            self.lock.release()
        return self._record(plan, result, started)
