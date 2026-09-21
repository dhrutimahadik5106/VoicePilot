"""Private calibration contracts and closed public outcomes."""
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field, field_validator, model_validator
from app.speaker.models import ModelIdentity
from app.planning.models import Model


class OwnerError(Exception):
    def __init__(self, code="access_denied"):
        allowed = {"access_denied", "calibration_required", "calibration_inconclusive",
                   "profile_missing", "profile_corrupt", "model_mismatch", "profile_changed",
                   "capture_quality_failed", "phrase_mismatch", "speaker_rejected",
                   "speaker_uncertain", "authentication_expired", "authentication_replayed",
                   "challenge_replayed", "challenge_expired", "binding_mismatch", "cancelled",
                   "consent_required", "invalid_transition", "duplicate_sample", "unsupported_command",
                   "confirmation_rejected", "confirmation_expired", "confirmation_replayed",
                   "storage_failed", "stt_rejected", "insufficient_samples", "concurrent_update"}
        self.code = code if code in allowed else "access_denied"
        super().__init__(self.code)


class Configuration(Model):
    calibration_enabled: bool = False
    pilot_enabled: bool = False
    phrase_version: Literal["owner-phrases-v1"] = "owner-phrases-v1"
    challenge_expiry: int = Field(default=45, ge=10, le=60)
    authentication_ttl: int = Field(default=60, ge=10, le=90)
    inactivity_timeout: int = Field(default=30, ge=5, le=45)
    maximum_commands: Literal[1] = 1
    minimum_owner_samples: int = Field(default=8, ge=8, le=32)
    minimum_holdout_samples: int = Field(default=4, ge=4, le=16)
    minimum_nonowner_samples: int = Field(default=20, ge=20, le=40)
    minimum_nonowner_speakers: int = Field(default=3, ge=3, le=10)
    minimum_replay_trials: int = Field(default=3, ge=3, le=10)
    acceptance_floor: float = Field(default=.80, ge=.80, le=.99, allow_inf_nan=False)
    rejection_floor: float = Field(default=.70, ge=.70, le=.90, allow_inf_nan=False)
    uncertainty_band: float = Field(default=.10, ge=.10, le=.20, allow_inf_nan=False)
    minimum_active_seconds: float = Field(default=1.5, ge=1.5, le=5, allow_inf_nan=False)
    minimum_active_fraction: float = Field(default=.4, ge=.4, le=1, allow_inf_nan=False)
    save_raw_audio: Literal[False] = False
    allowlist_version: Literal["owner-pilot-v1"] = "owner-pilot-v1"

    @field_validator("maximum_commands", "save_raw_audio", mode="before")
    @classmethod
    def fixed(cls, value, info):
        expected = 1 if info.field_name == "maximum_commands" else False
        if type(value) is type(expected) and value == expected or value == str(expected).lower():
            return expected
        raise ValueError()

    @field_validator("challenge_expiry", "authentication_ttl", "inactivity_timeout",
                     "minimum_owner_samples", "minimum_holdout_samples", "minimum_nonowner_samples",
                     "minimum_nonowner_speakers", "minimum_replay_trials", mode="before")
    @classmethod
    def integer(cls, value):
        if type(value) is str and value.isascii() and value.isdigit():
            return int(value)
        if type(value) is not int:
            raise ValueError()
        return value


class State(StrEnum):
    NOT_ENROLLED = "not_enrolled"
    ENROLLED = "enrolled_uncalibrated"
    OWNER = "collecting_owner_validation"
    OWNER_COMPLETE = "owner_validation_complete"
    NONOWNER = "collecting_impostor_validation"
    HOLDOUT = "collecting_owner_holdout"
    REPLAY = "replay_challenge_pending"
    EVALUATING = "evaluating"
    FAILED = "calibration_failed"
    INCONCLUSIVE = "calibration_inconclusive"
    CALIBRATED = "calibrated"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class Aggregate(Model):
    count: int = Field(ge=0, le=128, strict=True)
    minimum: float = Field(ge=-1, le=1, allow_inf_nan=False)
    maximum: float = Field(ge=-1, le=1, allow_inf_nan=False)
    sum: float = Field(ge=-128, le=128, allow_inf_nan=False)
    accepted: int = Field(ge=0, le=128, strict=True)
    retry_or_uncertain: int = Field(ge=0, le=128, strict=True)
    rejected: int = Field(ge=0, le=128, strict=True)

    @model_validator(mode="after")
    def consistent(self):
        if self.accepted + self.retry_or_uncertain + self.rejected > self.count:
            raise ValueError()
        if self.count and (self.minimum > self.maximum
                or not self.minimum * self.count - 1e-8 <= self.sum <= self.maximum * self.count + 1e-8):
            raise ValueError()
        return self


class ReplayCounts(Model):
    count: int = Field(ge=0, le=128, strict=True)
    rejected: int = Field(ge=0, le=128, strict=True)


class PrivateDocument(Model):
    profile: UUID
    provenance: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ModelIdentity
    configuration: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: UUID
    policy_version: Literal["owner-policy-v1"]
    consent: UUID
    created_at: str = Field(max_length=40)
    updated_at: str = Field(max_length=40)
    owner: Aggregate
    nonowner: Aggregate
    holdout: Aggregate
    replay: ReplayCounts
    owner_groups: list[Literal["quiet", "different_environment"]] = Field(max_length=2)
    nonowner_groups: list[Literal["quiet", "different_environment"]] = Field(max_length=2)
    holdout_groups: list[Literal["quiet", "different_environment"]] = Field(max_length=2)
    owner_phrases: list[int] = Field(max_length=12)
    nonowner_speakers: list[UUID] = Field(max_length=128)
    digests: list[str] = Field(max_length=128)
    captures: list[UUID] = Field(max_length=128)
    sessions: list[UUID] = Field(max_length=128)
    acceptance: float | None = Field(ge=.8, le=1, allow_inf_nan=False)
    rejection: float | None = Field(ge=.6, le=1, allow_inf_nan=False)
    frozen_at: str | None = Field(max_length=40)

    @model_validator(mode="after")
    def consistent(self):
        import re
        from datetime import datetime
        for name in ("digests", "captures", "sessions", "owner_groups", "nonowner_groups", "holdout_groups", "owner_phrases", "nonowner_speakers"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError()
        if not len(self.digests) == len(self.captures) == len(self.sessions):
            raise ValueError()
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in self.digests):
            raise ValueError()
        if any(type(value) is not int or not 0 <= value < 12 for value in self.owner_phrases):
            raise ValueError()
        if self.replay.rejected > self.replay.count:
            raise ValueError()
        created, updated = datetime.fromisoformat(self.created_at), datetime.fromisoformat(self.updated_at)
        if created.utcoffset() is None or updated.utcoffset() is None or updated < created:
            raise ValueError()
        if (self.acceptance is None) != (self.rejection is None) or (self.acceptance is None) != (self.frozen_at is None):
            raise ValueError()
        if self.acceptance is not None and self.acceptance - self.rejection < .099999:
            raise ValueError()
        return self

    def __repr__(self):
        return "PrivateDocument()"

    def __str__(self):
        return "PrivateDocument()"


class Record(Model):
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception:
            raise OwnerError("profile_corrupt") from None

    schema_version: Literal["owner-calibration-v1"] = "owner-calibration-v1"
    state: State = State.OWNER
    # Only explicit protected storage may serialize the private document.
    private: dict = Field(repr=False, exclude=True)

    @field_validator("private")
    @classmethod
    def validate_private(cls, value):
        try:
            return PrivateDocument.model_validate(value).model_dump(mode="json")
        except Exception:
            raise OwnerError("profile_corrupt") from None

    def document(self):
        return {"schema_version": self.schema_version, "state": self.state.value,
                "private": self.private}


class TrialConsent(Model):
    """Ephemeral selected-input consent; never an authentication or execution grant."""
    profile_id: UUID = Field(repr=False, exclude=True)
    group: Literal["owner", "nonowner", "holdout", "replay"] = Field(repr=False, exclude=True)
    environment: Literal["quiet", "different_environment"] = Field(repr=False, exclude=True)
    participant: UUID | None = Field(default=None, repr=False, exclude=True)


class Challenge(Model):
    handle: UUID = Field(default_factory=uuid4, repr=False, exclude=True)
    phrase: str = Field(repr=False, exclude=True)


class Evidence(Model):
    nonce: UUID = Field(default_factory=uuid4, repr=False, exclude=True)


class Outcome(Model):
    status: Literal["accepted", "retry_or_uncertain", "rejected"]
    reason: str = Field(pattern=r"^[a-z_]{1,50}$")
    evidence: Evidence | None = Field(default=None, repr=False, exclude=True)


class PilotResult(Model):
    status: Literal["completed", "blocked", "cancelled"]
    reason: str = Field(pattern=r"^[a-z_]{1,60}$")
    execution_permitted: bool = False
    volume_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    muted: bool | None = None
    brightness_percent: int | None = Field(default=None, ge=0, le=100, strict=True)
    application: Literal["notepad", "calculator", "chrome"] | None = None
    # Deliberate in-memory separation, never CLI/log/audit output.
    details: object | None = Field(default=None, repr=False, exclude=True)
