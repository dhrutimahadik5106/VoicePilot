"""Fake-only controller with atomic admission, bounded work and independent verification."""
import math
from threading import Event, Lock
from time import monotonic

from app.execution.adapters import FakeAdapter, FakeWorld, IndependentObserver, Scenario
from app.execution.authorization import FakeAuthority
from app.execution.models import Configuration, ExecutionError, Request, Result, State
from app.execution.registry import validate_plan, validate_step
from app.execution.state import Machine, TRANSITIONS


class Controller:
    def __init__(self, configuration=None, *, clock=monotonic):
        config = configuration or Configuration()
        self.configuration = Configuration.model_validate(config.model_dump())
        self.clock = clock
        self._stop = Event()
        self._lock = Lock()
        self._active = None
        self._ledger = set()
        self._world = FakeWorld()

    def emergency_stop(self):
        """Latched for this controller lifetime, including active fake work."""
        self._stop.set()
        active = self._active
        if active is not None:
            active.set()

    def run(self, *args, **kwargs):
        """Production entry point has no authorization or adapter path in Phase 5B."""
        return Result(state=State.BLOCKED, reason="disabled")

    def run_fake(self, plan, request, authority, *, scenario=Scenario.SUCCESS, cancel=None):
        if not self._lock.acquire(blocking=False):
            return Result(state=State.BLOCKED, reason="duplicate")
        machine = Machine()
        try:
            if self._stop.is_set():
                machine.move(State.BLOCKED, "emergency_stop")
                return Result(state=machine.state, reason="emergency_stop", events=tuple(machine.events))
            if cancel is not None and type(cancel) is not Event:
                raise ExecutionError()
            self._active = cancel if cancel is not None else Event()
            from app.execution.cancellation import GLOBAL
            with GLOBAL.track(self._active):
                return self._drive(machine, plan, request, authority, Scenario(scenario), self._active)
        except Exception:
            allowed = TRANSITIONS.get(machine.state, frozenset())
            target = next((state for state in (State.BLOCKED, State.FAILED, State.UNVERIFIED)
                           if state in allowed), State.BLOCKED)
            if target in allowed:
                machine.move(target, "invalid_request")
            return Result(state=target, reason="invalid_request", events=tuple(machine.events))
        finally:
            self._active = None
            self._lock.release()

    def _drive(self, machine, plan, request, authority, scenario, cancel):
        attempts = 0
        evidence = "none"
        start = self.clock()
        if not math.isfinite(start):
            raise ExecutionError()
        adapter = None

        def elapsed():
            value = self.clock() - start + (adapter.elapsed if adapter else 0)
            if not math.isfinite(value) or value < 0:
                raise ExecutionError()
            return value

        def result(reason, rollback=False):
            return Result(state=machine.state, reason=reason, attempts=attempts, evidence=evidence,
                          rollback_observed=rollback, events=tuple(machine.events))

        def interrupt():
            if self._stop.is_set() or cancel.is_set():
                cancel.set()
                reason = "emergency_stop" if self._stop.is_set() else "cancelled"
                machine.move(State.CANCELLED, reason, elapsed())
                return result(reason)
            if elapsed() >= self.configuration.timeout_seconds:
                cancel.set()
                machine.move(State.TIMED_OUT, "timeout", elapsed())
                return result("timeout")
            return None

        machine.move(State.VALIDATING)
        plan = validate_plan(plan)
        if type(request) is not Request or type(authority) is not FakeAuthority:
            raise ExecutionError()
        step = next((s for s in plan.steps if s.step_id == request.binding.step_id), None)
        if step is None:
            raise ExecutionError()
        spec = validate_step(step)
        machine.plan_id, machine.step_id, machine.capability = plan.plan_id, step.step_id, step.capability
        if cancel.is_set():
            machine.move(State.CANCELLED, "cancelled")
            return result("cancelled")
        machine.move(State.AWAITING)
        if not authority.consume(plan, request):
            machine.move(State.BLOCKED, "unauthorized")
            return result("unauthorized")
        machine.move(State.AUTHORIZED)
        key = (plan.plan_id, step.step_id)
        if key in self._ledger or len(self._ledger) >= self.configuration.max_entries:
            machine.move(State.BLOCKED, "duplicate")
            return result("duplicate")
        stopped = interrupt()
        if stopped:
            return stopped
        # Reserve even unsuccessful work: a fresh token cannot repeat this logical effect.
        self._ledger.add(key)
        adapter = FakeAdapter(step.capability, self._world, scenario)
        observer = IndependentObserver(self._world)
        before = observer.observe(key)
        if not adapter.precondition(step):
            machine.move(State.BLOCKED, "precondition_failed")
            return result("precondition_failed")
        machine.move(State.RUNNING)
        try:
            limit = 1 + (self.configuration.max_retries if spec.idempotent else 0)
            for attempt in range(1, limit + 1):
                stopped = interrupt()
                if stopped:
                    return stopped
                attempts = attempt
                returned = adapter.execute(key, step, cancel)
                evidence = "adapter_returned"
                stopped = interrupt()
                if stopped:
                    return stopped
                if returned:
                    break
                if attempt < limit:
                    machine.move(State.RUNNING, "retry", elapsed())
            if not returned:
                machine.move(State.FAILED, "adapter_failed", elapsed())
            else:
                machine.move(State.OBSERVING, duration=elapsed())
                after = observer.observe(key, available=scenario != Scenario.NO_OBSERVATION)
                stopped = interrupt()
                if stopped:
                    return stopped
                if not after.available:
                    evidence = "observation_unavailable"
                    machine.move(State.UNVERIFIED, "observation_unavailable", elapsed())
                else:
                    evidence = "observation_available"
                    machine.move(State.VERIFYING, duration=elapsed())
                    verified = observer.verify(key, step, before, after)
                    stopped = interrupt()
                    if stopped:
                        return stopped
                    if verified:
                        evidence = "verified_success"
                        machine.move(State.SUCCEEDED, duration=elapsed())
                        return result("ok")
                    evidence = "verification_failed"
                    machine.move(State.FAILED, "verification_failed", elapsed())
            if not spec.rollback_supported:
                return result("adapter_failed")
            machine.move(State.ROLLBACK_PENDING, duration=elapsed())
            stopped = interrupt()
            if stopped:
                return stopped
            adapter.rollback(key, before, cancel)
            restored = observer.observe(key, available=scenario != Scenario.NO_OBSERVATION)
            stopped = interrupt()
            if stopped:
                return stopped
            if observer.restored(key, before, restored):
                machine.move(State.ROLLED_BACK, "rollback_verified", elapsed())
                return result("rollback_verified", rollback=True)
            machine.move(State.UNVERIFIED, "rollback_unverified", elapsed())
            return result("rollback_unverified")
        except Exception:
            target = State.UNVERIFIED if machine.state in {State.OBSERVING, State.ROLLBACK_PENDING} else State.FAILED
            if target in TRANSITIONS.get(machine.state, set()):
                machine.move(target, "adapter_failed")
            return Result(state=target, reason="adapter_failed", attempts=attempts,
                          evidence=evidence, events=tuple(machine.events))
