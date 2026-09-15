"""Closed execution contracts; sensitive bindings never enter routine output."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator
from app.planning.models import Model, Arguments, Capability, Risk


class ExecutionError(Exception):
    def __init__(self):
        super().__init__("execution_rejected")


class Configuration(Model):
    enabled: Literal[False] = False
    fake_only: Literal[True] = True
    policy_version: Literal["5b-v1"] = "5b-v1"
    timeout_seconds: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    max_retries: int = Field(default=1, ge=0, le=3, strict=True)
    evidence_ttl: int = Field(default=60, ge=1, le=300, strict=True)
    max_entries: int = Field(default=1000, ge=1, le=10000, strict=True)

    @field_validator("enabled", "fake_only", mode="before")
    @classmethod
    def switches(cls, value, info):
        expected = info.field_name == "fake_only"
        if value is expected or value == str(expected).lower():
            return expected
        raise ValueError()

    @field_validator("max_retries", "evidence_ttl", "max_entries", mode="before")
    @classmethod
    def integers(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        return value

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError()
        return value


class State(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"
    AWAITING = "awaiting_authorization"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    ROLLBACK_PENDING = "rollback_pending"
    ROLLED_BACK = "rolled_back"
    UNVERIFIED = "unverified"


Reason = Literal["ok", "disabled", "invalid_request", "unauthorized", "emergency_stop",
                 "cancelled", "timeout", "adapter_failed", "observation_unavailable",
                 "verification_failed", "rollback_verified", "rollback_unverified",
                 "duplicate", "retry", "precondition_failed"]


class FakeStep(Model):
    step_id: str = Field(pattern=r"^step-[1-9][0-9]?$", max_length=7)
    capability: Capability
    arguments: Arguments = Field(repr=False, exclude=True)
    expected_condition: Literal["synthetic_effect_present"] = "synthetic_effect_present"
    risk: Risk = Risk.LOW
    requires_confirmation: Literal[True] = True
    execution_permitted: Literal[False] = False


class FakePlan(Model):
    """Separate synthetic fixture, never a promotion of a diagnostic Plan."""
    plan_id: UUID = Field(default_factory=uuid4)
    version: Literal["5b-fixture-v1"] = "5b-fixture-v1"
    origin: Literal["synthetic_fixture"] = "synthetic_fixture"
    steps: tuple[FakeStep, ...] = Field(min_length=1, max_length=10)
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def unique_steps(self):
        if len({step.step_id for step in self.steps}) != len(self.steps):
            raise ValueError()
        return self


class Binding(Model):
    plan_id: UUID
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$", repr=False, exclude=True)
    step_id: str = Field(pattern=r"^step-[1-9][0-9]?$", max_length=7)
    step_digest: str = Field(pattern=r"^[a-f0-9]{64}$", repr=False, exclude=True)
    capability: Capability
    arguments: Arguments = Field(repr=False, exclude=True)
    authentication_id: UUID = Field(repr=False, exclude=True)
    confirmation_id: UUID = Field(repr=False, exclude=True)
    policy_version: Literal["5b-v1"] = "5b-v1"
    expires_at: datetime = Field(repr=False, exclude=True)
    nonce: UUID = Field(default_factory=uuid4, repr=False, exclude=True)
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def utc(self):
        if self.expires_at.utcoffset() is None or self.expires_at.utcoffset().total_seconds() != 0:
            raise ValueError()
        return self


class Authorization(Model):
    handle: UUID = Field(default_factory=uuid4, repr=False, exclude=True)
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False


class Authentication(Authorization):
    pass


class Confirmation(Authorization):
    pass


class Request(Model):
    binding: Binding = Field(repr=False, exclude=True)
    authorization: Authorization = Field(repr=False, exclude=True)
    execution_permitted: Literal[False] = False


class AuditEvent(Model):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    plan_id: UUID | None = None
    step_id: str | None = Field(default=None, pattern=r"^step-[1-9][0-9]?$", max_length=7)
    capability: Capability | None = None
    previous: State
    state: State
    reason: Reason
    duration: float = Field(default=0, ge=0, allow_inf_nan=False)
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def utc(self):
        if self.timestamp.utcoffset() is None or self.timestamp.utcoffset().total_seconds() != 0:
            raise ValueError()
        return self


class Result(Model):
    state: State
    reason: Reason
    attempts: int = Field(default=0, ge=0, le=4)
    evidence: Literal["none", "adapter_returned", "observation_available", "verified_success",
                      "verification_failed", "observation_unavailable"] = "none"
    rollback_observed: bool = False
    events: tuple[AuditEvent, ...] = ()
    fake: Literal[True] = True
    execution_permitted: Literal[False] = False
    real_actions: Literal[0] = 0

    @model_validator(mode="after")
    def success_requires_evidence(self):
        if self.state == State.SUCCEEDED and self.evidence != "verified_success":
            raise ValueError()
        if (self.state == State.ROLLED_BACK) != self.rollback_observed:
            raise ValueError()
        return self
