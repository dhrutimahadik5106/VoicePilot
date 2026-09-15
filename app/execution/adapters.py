"""In-memory fakes and an independent reader; no operating-system adapters."""
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field
from app.planning.models import Model, Capability
from app.execution.models import FakeStep
from app.execution.registry import AdapterSpec, REGISTRY


class Scenario(StrEnum):
    SUCCESS = "success"
    FAIL = "adapter_failure"
    FALSE_SUCCESS = "false_adapter_success"
    NO_OBSERVATION = "observation_failure"
    WRONG_EFFECT = "verification_failure"
    CANCEL = "cancellation"
    TIMEOUT = "timeout"
    ROLLBACK_FAIL = "rollback_failure"
    ROLLBACK_LIE = "rollback_false_success"
    TRANSIENT = "transient_failure"
    EXCEPTION = "adapter_exception"
    PRECONDITION = "precondition_failure"


class Observation(Model):
    plan_id: UUID
    step_id: str = Field(pattern=r"^step-[1-9][0-9]?$", max_length=7)
    count: int = Field(ge=0, le=10000, strict=True)
    available: bool = True
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False


class Adapter(Protocol):
    spec: AdapterSpec
    input_schema: type

    def precondition(self, step: FakeStep) -> bool: ...
    def execute(self, key: tuple[UUID, str], step: FakeStep, cancel: Event) -> bool: ...
    def observe(self, key: tuple[UUID, str]) -> Observation: ...
    def verify(self, step: FakeStep, before: Observation, after: Observation) -> bool: ...
    def rollback(self, key: tuple[UUID, str], before: Observation, cancel: Event) -> bool: ...


@dataclass
class FakeWorld:
    values: dict[tuple[UUID, str], int] = field(default_factory=dict)


class IndependentObserver:
    def __init__(self, world):
        self.world = world

    def observe(self, key, *, available=True):
        return Observation(plan_id=key[0], step_id=key[1],
                           count=self.world.values.get(key, 0), available=available)

    def verify(self, key, step, before, after):
        if (not before.available or not after.available or not before.fake or not after.fake
                or (before.plan_id, before.step_id) != key or (after.plan_id, after.step_id) != key):
            return False
        expected = 1 if step.capability == Capability.LAUNCH else before.count + 1
        return after.count == expected

    def restored(self, key, before, after):
        return after.available and (after.plan_id, after.step_id) == key and after.count == before.count


class FakeAdapter:
    """Adapter observations are advisory; the controller reads FakeWorld separately."""
    input_schema = FakeStep

    def __init__(self, capability, world, scenario=Scenario.SUCCESS):
        self.spec = REGISTRY[capability]
        self.world = world
        self.scenario = Scenario(scenario)
        self.calls = 0
        self.elapsed = 0.0

    def precondition(self, step):
        return step.capability == self.spec.capability and self.scenario != Scenario.PRECONDITION

    def execute(self, key, step, cancel):
        self.calls += 1
        if cancel.is_set():
            return False
        if self.scenario == Scenario.CANCEL:
            cancel.set()
            return False
        if self.scenario == Scenario.TIMEOUT:
            self.elapsed += 31.0
            return False
        if self.scenario == Scenario.EXCEPTION:
            raise RuntimeError("fake_adapter_failure")
        if self.scenario == Scenario.FAIL or self.scenario == Scenario.TRANSIENT and self.calls == 1:
            return False
        if self.scenario == Scenario.FALSE_SUCCESS:
            return True
        wrong = self.scenario in {Scenario.WRONG_EFFECT, Scenario.ROLLBACK_FAIL, Scenario.ROLLBACK_LIE}
        self.world.values[key] = 99 if wrong else (
            1 if step.capability == Capability.LAUNCH else self.world.values.get(key, 0) + 1)
        return True

    def observe(self, key):
        return IndependentObserver(self.world).observe(key)

    def verify(self, step, before, after):
        return IndependentObserver(self.world).verify((after.plan_id, after.step_id), step, before, after)

    def rollback(self, key, before, cancel):
        if cancel.is_set() or self.scenario == Scenario.ROLLBACK_FAIL:
            return False
        if self.scenario == Scenario.ROLLBACK_LIE:
            return True
        self.world.values[key] = before.count
        return True
