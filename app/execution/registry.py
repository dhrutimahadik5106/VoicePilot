"""Closed immutable fake capability metadata, never dynamic import instructions."""
from types import MappingProxyType
from typing import Literal
from app.planning.models import Model, Capability, Risk
from app.execution.models import FakePlan, FakeStep, ExecutionError


class AdapterSpec(Model):
    adapter_id: Literal["fake.launch.v1", "fake.play.v1"]
    capability: Capability
    idempotent: bool
    rollback_supported: bool
    cancellation_supported: Literal[True] = True
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False


REGISTRY = MappingProxyType({
    Capability.LAUNCH: AdapterSpec(adapter_id="fake.launch.v1", capability=Capability.LAUNCH,
                                  idempotent=True, rollback_supported=True),
    Capability.PLAY: AdapterSpec(adapter_id="fake.play.v1", capability=Capability.PLAY,
                                idempotent=False, rollback_supported=True),
})


def step_document(step):
    return step.model_dump(mode="json") | {"arguments": step.arguments.model_dump(mode="json")}


def plan_document(plan):
    if type(plan) is not FakePlan:
        raise ExecutionError()
    return plan.model_dump(mode="json") | {"steps": [step_document(s) for s in plan.steps]}


def validate_plan(plan):
    try:
        checked = FakePlan.model_validate(plan_document(plan))
        for step in checked.steps:
            validate_step(step)
        return checked
    except Exception:
        raise ExecutionError() from None


def validate_step(step):
    if type(step) is not FakeStep or step.capability not in REGISTRY or step.risk != Risk.LOW:
        raise ExecutionError()
    args = step.arguments
    if args.control is not None or args.application not in {"spotify", "chrome"}:
        raise ExecutionError()
    if step.capability == Capability.LAUNCH and args.media is not None:
        raise ExecutionError()
    if step.capability == Capability.PLAY and (args.application != "spotify" or args.media is None):
        raise ExecutionError()
    return REGISTRY[step.capability]
