"""Closed Phase 6B contracts and safe errors."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field, field_validator, model_validator
from app.planning.models import Model
from app.execution.models import State


class Capability(StrEnum):
    VOLUME_READ = "system.volume.read"
    MUTE_READ = "system.volume.mute.read"
    VOLUME_UP = "system.volume.increase"
    VOLUME_DOWN = "system.volume.decrease"
    VOLUME_SET = "system.volume.set"
    MUTE = "system.volume.mute"
    UNMUTE = "system.volume.unmute"
    BRIGHTNESS_READ = "system.brightness.read"
    BRIGHTNESS_UP = "system.brightness.increase"
    BRIGHTNESS_DOWN = "system.brightness.decrease"
    BRIGHTNESS_SET = "system.brightness.set"
    SCREENSHOT = "screen.screenshot.capture"
    SCREENSHOT_DELETE = "screen.screenshot.delete"
    CANCEL = "execution.cancel"
    STOP = "execution.stop"
    HISTORY = "history.session.inspect"


class Code(StrEnum):
    READ = "state_read_and_verified"
    CHANGED = "changed_and_verified"
    ALREADY = "already_in_expected_state"
    CAPTURED = "capture_saved_and_verified"
    DELETED = "selected_artifact_deleted_and_verified"
    CANCEL_REQUESTED = "cancel_requested"
    NOTHING_ACTIVE = "nothing_active"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid_argument"
    CONFIRMATION = "confirmation_required"
    DECLINED = "confirmation_declined"
    EXPIRED = "authorization_expired"
    REPLAYED = "authorization_replayed"
    DENIED = "access_denied"
    FAILED = "operation_failed"
    NO_OBSERVATION = "observation_unavailable"
    UNVERIFIED = "verification_failed"
    TIMEOUT = "timed_out"
    CANCELLED = "cancelled"
    STOPPED = "emergency_stopped"


class OperationError(Exception):
    def __init__(self, code=Code.FAILED):
        self.code = code if type(code) is Code else Code.FAILED
        super().__init__(self.code.value)


class Configuration(Model):
    enabled: bool = False
    manual_testing_enabled: bool = True
    screenshot_enabled: bool = False
    volume_step: int = Field(default=5, ge=1, le=10, strict=True)
    brightness_step: int = Field(default=5, ge=1, le=10, strict=True)
    volume_tolerance: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    operation_timeout: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    observation_timeout: float = Field(default=2, gt=0, le=10, allow_inf_nan=False)
    authorization_expiry: int = Field(default=30, ge=1, le=60, strict=True)
    history_limit: int = Field(default=100, ge=1, le=1000, strict=True)
    maximum_actions: Literal[1] = 1

    @field_validator("volume_step", "brightness_step", "authorization_expiry", "history_limit", mode="before")
    @classmethod
    def integer_setting(cls, value):
        if type(value) is str and value.isascii() and value.isdigit():
            return int(value)
        return value

    @field_validator("maximum_actions", mode="before")
    @classmethod
    def one(cls, value):
        if type(value) is int and value == 1 or type(value) is str and value == "1":
            return 1
        raise ValueError()

    @field_validator("volume_tolerance", "operation_timeout", "observation_timeout", mode="before")
    @classmethod
    def numbers(cls, value):
        if type(value) is bool:
            raise ValueError()
        return value


class Plan(Model):
    action_id: UUID = Field(default_factory=uuid4)
    version: Literal["6b-v1"] = "6b-v1"
    step_id: Literal["step-1"] = "step-1"
    capability: Capability
    percentage: int | None = Field(default=None, ge=0, le=100, strict=True, repr=False, exclude=True)
    artifact_id: UUID | None = Field(default=None, repr=False, exclude=True)
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def arguments(self):
        if (self.percentage is not None) != (self.capability in {Capability.VOLUME_SET, Capability.BRIGHTNESS_SET}):
            raise ValueError()
        if (self.artifact_id is not None) != (self.capability == Capability.SCREENSHOT_DELETE):
            raise ValueError()
        return self


def validate_plan(plan):
    if type(plan) is not Plan:
        raise OperationError(Code.INVALID)
    try:
        return Plan.model_validate(plan.model_dump() | {"percentage": plan.percentage, "artifact_id": plan.artifact_id})
    except Exception:
        raise OperationError(Code.INVALID) from None


class Permit(Model):
    token: UUID = Field(default_factory=uuid4, repr=False, exclude=True)


class Volume(Model):
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    muted: bool = Field(strict=True)
    endpoint: str = Field(min_length=1, max_length=4096, repr=False, exclude=True)


class Brightness(Model):
    supported: bool
    percent: int | None = Field(default=None, ge=0, le=100, strict=True)
    mutation_supported: bool = False
    target: str = Field(default="internal", repr=False, exclude=True)


class Event(Model):
    action_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    capability: Capability
    code: Code
    duration: float = Field(ge=0, le=3600, allow_inf_nan=False)
    fake: bool
    confirmation_required: bool
    execution_permitted: bool


class Transition(Model):
    plan_id: UUID | None
    step_id: Literal["step-1"] | None
    capability: Capability | None
    previous: State
    state: State
    reason: Code
    duration: float = Field(default=0, ge=0, allow_inf_nan=False)


class Result(Model):
    action_id: UUID = Field(default_factory=uuid4)
    code: Code
    verified: bool = False
    execution_permitted: bool = False
    fake: bool = False
    mutation_attempted: bool = False
    recovery: Literal["not_needed", "previous_state_observed", "not_restored", "unknown"] = "not_needed"
    rollback_performed: Literal[False] = False
    volume: Volume | None = None
    brightness: Brightness | None = None
    artifact_id: UUID | None = None
    transitions: tuple[Transition, ...] = ()

    @model_validator(mode="after")
    def success_evidence(self):
        if self.code in {Code.READ, Code.CHANGED, Code.ALREADY, Code.CAPTURED, Code.DELETED} and not self.verified:
            raise ValueError()
        return self
