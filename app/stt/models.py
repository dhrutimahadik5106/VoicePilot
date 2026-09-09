"""Validated transcription data; text/audio are excluded from representations."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.audio.models import RecordedAudio
from app.core.config import normalize_stt_language


class TranscriptionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscriptionErrorCode(StrEnum):
    EMPTY_AUDIO = "empty_audio"
    AUDIO_TOO_LONG = "audio_too_long"
    FILE_NOT_FOUND = "file_not_found"
    INVALID_WAV = "invalid_wav"
    UNSUPPORTED_AUDIO = "unsupported_audio"
    PERMISSION_DENIED = "permission_denied"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    TRANSCRIPTION_FAILED = "transcription_failed"
    CANCELLED = "cancelled"
    BUSY = "busy"


class SafeTranscriptionError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: TranscriptionErrorCode


class TranscriptionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    audio: RecordedAudio = Field(repr=False)
    language: str | None = None
    audio_id: UUID = Field(default_factory=uuid4)
    execution_correlation_id: UUID | None = None

    @field_validator("language", mode="before")
    @classmethod
    def validate_language(cls, value):
        return normalize_stt_language(value)


class WordTimestamp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(repr=False)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end < self.start:
            raise ValueError("Invalid word interval")
        return self


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(repr=False)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    words: tuple[WordTimestamp, ...] = Field(default=(), repr=False)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.end < self.start:
            raise ValueError("Invalid segment interval")
        if any(word.start < self.start or word.end > self.end for word in self.words):
            raise ValueError("Word outside segment")
        if any(a.start > b.start for a, b in zip(self.words, self.words[1:])):
            raise ValueError("Words out of order")
        return self


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    audio_id: UUID
    execution_correlation_id: UUID | None = None
    text: str = Field(default="", repr=False)
    language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    segments: tuple[TranscriptSegment, ...] = Field(default=(), repr=False)
    processing_duration: float = Field(ge=0, allow_inf_nan=False)
    model_load_duration: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    inference_duration: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    cold_start: bool | None = None
    source_audio_duration: float = Field(ge=0, le=120, allow_inf_nan=False)
    model_name: str
    device: str
    compute_type: str
    status: TranscriptionStatus
    error: SafeTranscriptionError | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_result(self):
        if self.model_load_duration + self.inference_duration > self.processing_duration + 1e-6:
            raise ValueError("Component timings exceed total processing duration")
        if self.cold_start is False and self.model_load_duration != 0:
            raise ValueError("Warm inference cannot include model loading")
        if self.timestamp.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        if self.status == TranscriptionStatus.SUCCEEDED:
            if self.error is not None or self.source_audio_duration <= 0 or not self.language:
                raise ValueError("Invalid successful result")
            if self.text != " ".join(segment.text.strip() for segment in self.segments if segment.text.strip()):
                raise ValueError("Transcript does not match segments")
            if any(a.start > b.start for a, b in zip(self.segments, self.segments[1:])):
                raise ValueError("Segments out of order")
        elif self.error is None or self.text or self.segments or self.language_probability is not None:
            raise ValueError("Unsuccessful transcription must discard text")
        if self.status == TranscriptionStatus.CANCELLED and self.error.code != TranscriptionErrorCode.CANCELLED:
            raise ValueError("Invalid cancellation code")
        return self

    @computed_field(repr=False)
    @property
    def raw_transcript(self) -> str:
        """Exact segment text concatenation in chronological order."""
        return "".join(segment.text for segment in self.segments)

    @computed_field(repr=False)
    @property
    def normalized_transcript(self) -> str:
        """Only trim/join segment-boundary whitespace; never substitute words."""
        return self.text

    @computed_field
    @property
    def total_processing_duration(self) -> float:
        return self.processing_duration

    @computed_field
    @property
    def real_time_factor(self) -> float | None:
        """Processing seconds per source-audio second; not an accuracy metric."""
        return self.processing_duration / self.source_audio_duration if self.source_audio_duration else None

    @property
    def error_code(self) -> TranscriptionErrorCode | None:
        return self.error.code if self.error is not None else None
