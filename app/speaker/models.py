"""Strict public metadata; biometric values have a separate private boundary."""
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Status = Literal["verified", "rejected", "uncertain", "unavailable", "cancelled", "invalid_audio", "invalid_profile"]
Reason = Literal["ok", "consent_required", "persistence_consent_required", "cancelled",
    "invalid_audio", "invalid_embedding", "inconsistent_samples", "sample_count",
    "duplicate_sample", "unavailable", "invalid_profile", "incompatible_profile",
    "calibration_pending", "below_threshold", "review_required", "backend_failed",
    "binding_mismatch", "stt_rejected", "downstream_failed", "runtime_unavailable", "model_missing", "model_invalid", "inference_failed", "protection_unavailable", "protection_failed", "provisioning_failed"]

class SafeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True,
                              arbitrary_types_allowed=True)

class SpeakerConfiguration(SafeModel):
    profile_root: Path | None = Field(default=None, repr=False, exclude=True)
    model_path: Path | None = Field(default=None, repr=False, exclude=True)
    policy_path: Path | None = Field(default=None, repr=False, exclude=True)
    model_id: Literal["wespeaker-resnet34"] = "wespeaker-resnet34"
    backend: Literal["sherpa-onnx"] = "sherpa-onnx"
    checksum: str = Field(default="5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94", pattern=r"^[0-9a-f]{64}$")
    checksum_type: Literal["publisher-sha256"] = "publisher-sha256"
    default_profile_id: UUID | None = Field(default=None, repr=False, exclude=True)
    calibration_root: Path | None = Field(default=None, repr=False, exclude=True)
    calibration_state: Literal["pending", "validated"] = "pending"
    diagnostics: bool = False
    max_retries: int = Field(default=2, ge=0, le=3, strict=True)
    capture_duration: float = Field(default=8.0, gt=0, le=120, allow_inf_nan=False)
    schema_version: Literal[1] = 1
    sample_rate: Literal[16000] = 16000
    embedding_dimension: int = Field(default=256, ge=2, le=4096, strict=True)
    min_samples: int = Field(default=3, ge=3, le=5, strict=True)
    max_samples: int = Field(default=5, ge=3, le=5, strict=True)
    enrollment_samples: int = Field(default=4, ge=3, le=5, strict=True)
    min_duration: float = Field(default=3.0, gt=0, le=120, allow_inf_nan=False)
    max_duration: float = Field(default=30.0, gt=0, le=120, allow_inf_nan=False)
    min_rms: float = Field(default=.005, gt=0, le=1, allow_inf_nan=False)
    max_clipping: float = Field(default=.01, ge=0, le=1, allow_inf_nan=False)
    consistency_threshold: float = Field(default=.7, ge=-1, le=1, allow_inf_nan=False)
    acceptance_threshold: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    rejection_threshold: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    policy_version: str = Field(default="calibration-pending", pattern=r"^[a-z0-9-]{1,64}$")
    secure_profiles_required: Literal[True] = True
    local_files_only: Literal[True] = True
    antispoof_policy: Literal["not_assessed"] = "not_assessed"

    @field_validator("sample_rate", "schema_version", "embedding_dimension", "min_samples", "max_samples", "enrollment_samples", "max_retries", mode="before")
    @classmethod
    def environment_integer(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        if isinstance(value, bool):
            raise ValueError("invalid_integer_setting")
        return value

    @field_validator("secure_profiles_required", "local_files_only", mode="before")
    @classmethod
    def required_guard(cls, value):
        if value is True or value == "true":
            return True
        raise ValueError("required_guard_disabled")

    @field_validator("min_duration", "max_duration", "min_rms", "max_clipping", "consistency_threshold", "acceptance_threshold", "rejection_threshold", "capture_duration", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("invalid_numeric_setting")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if not self.min_samples <= self.enrollment_samples <= self.max_samples:
            raise ValueError("invalid_sample_bounds")
        if self.min_duration > self.max_duration:
            raise ValueError("invalid_duration_bounds")
        if self.rejection_threshold is not None and (self.acceptance_threshold is None
                or self.rejection_threshold > self.acceptance_threshold):
            raise ValueError("invalid_threshold_order")
        return self

class ModelIdentity(SafeModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    revision: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    dimension: int = Field(ge=2, le=4096, strict=True)

class ThresholdConfiguration(SafeModel):
    version: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    model: ModelIdentity
    acceptance: float = Field(ge=-1, le=1, allow_inf_nan=False)
    review: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    calibration: Literal["pending", "synthetic", "validated"] = "pending"
    @field_validator("acceptance", "review", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("invalid_threshold")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.review is not None and self.review > self.acceptance:
            raise ValueError("invalid_threshold_order")
        return self

class EnrollmentConsent(SafeModel):
    enrollment: bool = Field(default=False, strict=True)
    persistence: bool = Field(default=False, strict=True)

class SpeakerQualitySummary(SafeModel):
    eligible: bool
    reason: Literal["ok", "invalid_audio"] = "invalid_audio"
    duration: float = Field(default=0, ge=0, le=120, allow_inf_nan=False)
    rms: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    peak: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    clipping: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    samples: int = Field(default=0, ge=0, le=5760000)
    channels: int = Field(default=0, ge=0, le=2)
    sample_rate: int = Field(default=0, ge=0, le=48000)

class EnrollmentSampleResult(SafeModel):
    sample_id: UUID
    accepted: bool
    quality: SpeakerQualitySummary
    reason: Reason

class SpeakerProfile(SafeModel):
    def __init__(self, **data):
        from app.speaker.contracts import SpeakerError
        try:
            super().__init__(**data)
        except Exception:
            # Pydantic errors() can include raw input even with hidden error text.
            # No ValidationError carrying a private payload crosses this boundary.
            raise SpeakerError("invalid_profile") from None

    schema_version: Literal[1] = 1
    profile_id: UUID
    model: ModelIdentity
    template: object = Field(repr=False, exclude=True)
    enrollment_session: UUID | None = None
    enrollment_hashes: tuple[str, ...] = Field(default=(), repr=False, exclude=True)
    sample_count: int = Field(ge=3, le=5, strict=True)
    created_at: datetime
    updated_at: datetime
    policy_version: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    calibration: Literal["pending", "synthetic", "validated"] = "pending"
    @model_validator(mode="after")
    def validate_profile(self):
        from app.speaker.embedding import normalized
        import numpy as np
        raw = self.template
        vector = normalized(raw, self.model.dimension)
        if not np.isclose(np.linalg.norm(np.asarray(raw, dtype=np.float64)), 1, atol=1e-6):
            raise ValueError("invalid_template")
        if (self.created_at.utcoffset() is None or self.updated_at.utcoffset() is None
                or self.updated_at < self.created_at):
            raise ValueError("invalid_timestamps")
        # Preserve the validated exact bytes across protected round trips.
        object.__setattr__(self, "template", np.frombuffer(np.asarray(raw, dtype=np.float64).tobytes(), dtype=np.float64))
        return self

class EnrollmentResult(SafeModel):
    status: Literal["enrolled", "rejected", "unavailable", "cancelled"]
    profile_id: UUID | None = None
    reason: Reason
    samples: tuple[EnrollmentSampleResult, ...] = ()

class AntiSpoofingResult(SafeModel):
    status: Literal["acceptable", "suspected_replay", "suspected_synthetic", "unknown", "unavailable"]
    assurance: Literal["not_assessed"] = "not_assessed"

class VerificationResult(SafeModel):
    attempt_id: UUID
    audio_id: UUID
    profile_id: UUID
    model: ModelIdentity | None = None
    status: Status
    reason: Reason
    similarity: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    policy: ThresholdConfiguration | None = None
    quality: SpeakerQualitySummary | None = None
    processing_duration: float = Field(default=0, ge=0, allow_inf_nan=False)
    spoof_assurance: Literal["not_assessed"] = "not_assessed"
    @model_validator(mode="after")
    def verified_metadata(self):
        if self.status == "verified" and (self.similarity is None or self.policy is None
                or self.policy.calibration == "pending" or self.model != self.policy.model
                or self.similarity < self.policy.acceptance or self.quality is None
                or not self.quality.eligible):
            raise ValueError("invalid_verified_result")
        return self

class PipelineResult(SafeModel):
    status: Literal["blocked", "completed", "cancelled"]
    reason: Reason
    verification: VerificationResult | None = None
    transcription: object | None = Field(default=None, repr=False, exclude=True)
    resolution: object | None = Field(default=None, repr=False, exclude=True)
    execution_permitted: Literal[False] = False
