"""Process-local, exact-action operator consent; not voice authentication."""
from hashlib import sha256
from threading import Lock
from time import monotonic
from app.operations.models import Permit, OperationError, Code, validate_plan


def binding(plan):
    plan = validate_plan(plan)
    return sha256((plan.model_dump_json() + str(plan.percentage) + str(plan.artifact_id)).encode()).hexdigest()


def confirmation(plan):
    plan = validate_plan(plan)
    suffix = " " + str(plan.percentage) if plan.percentage is not None else ""
    if plan.artifact_id is not None:
        suffix += " " + str(plan.artifact_id)
    return "APPROVE " + plan.capability.value + suffix


class ManualAuthority:
    def __init__(self, configuration, *, clock=monotonic):
        self.configuration = configuration
        self.clock = clock
        self.records = {}
        self.used = set()
        self.lock = Lock()

    def issue(self, plan, response):
        with self.lock:
            if not self.configuration.manual_testing_enabled:
                raise OperationError(Code.DENIED)
            if response != confirmation(plan):
                raise OperationError(Code.DECLINED)
            if len(self.records) + len(self.used) >= 1000 or plan.action_id in self.used:
                raise OperationError(Code.REPLAYED)
            permit = Permit()
            self.records[permit.token] = (binding(plan), self.clock() + self.configuration.authorization_expiry)
            return permit

    def consume(self, plan, permit):
        with self.lock:
            if type(permit) is not Permit:
                raise OperationError(Code.CONFIRMATION)
            record = self.records.pop(permit.token, None)
            if record is None or plan.action_id in self.used:
                raise OperationError(Code.REPLAYED)
            if self.clock() >= record[1]:
                raise OperationError(Code.EXPIRED)
            if record[0] != binding(plan):
                raise OperationError(Code.DENIED)
            self.used.add(plan.action_id)
            return record[1]
