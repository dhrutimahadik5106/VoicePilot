"""Validated finite state transitions and allowlisted in-memory audit events."""
from types import MappingProxyType
from app.execution.models import AuditEvent, ExecutionError, State


TRANSITIONS = {
    State.CREATED: {State.VALIDATING, State.BLOCKED},
    State.VALIDATING: {State.AWAITING, State.BLOCKED, State.CANCELLED},
    State.AWAITING: {State.AUTHORIZED, State.BLOCKED, State.CANCELLED},
    State.AUTHORIZED: {State.RUNNING, State.BLOCKED, State.CANCELLED, State.TIMED_OUT},
    State.RUNNING: {State.RUNNING, State.OBSERVING, State.FAILED, State.CANCELLED, State.TIMED_OUT},
    State.OBSERVING: {State.VERIFYING, State.UNVERIFIED, State.CANCELLED, State.TIMED_OUT},
    State.VERIFYING: {State.SUCCEEDED, State.FAILED, State.CANCELLED, State.TIMED_OUT},
    State.FAILED: {State.ROLLBACK_PENDING},
    State.UNVERIFIED: {State.ROLLBACK_PENDING},
    State.ROLLBACK_PENDING: {State.ROLLED_BACK, State.UNVERIFIED, State.CANCELLED, State.TIMED_OUT},
}

TRANSITIONS = MappingProxyType({state: frozenset(targets) for state, targets in TRANSITIONS.items()})


class Machine:
    def __init__(self, *, event_factory=AuditEvent):
        self.event_factory = event_factory
        self.state = State.CREATED
        self.events = []
        self.plan_id = None
        self.step_id = None
        self.capability = None

    def move(self, state, reason="ok", duration=0):
        if state not in TRANSITIONS.get(self.state, set()):
            raise ExecutionError()
        event = self.event_factory(plan_id=self.plan_id, step_id=self.step_id, capability=self.capability,
                           previous=self.state, state=state, reason=reason, duration=duration)
        self.events.append(event)
        self.state = state
