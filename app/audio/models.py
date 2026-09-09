"""Validated in-memory PCM models. Sample data is excluded from representations."""
from datetime import datetime
from enum import StrEnum
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ErrorCode(StrEnum):
    DEVICE_NOT_FOUND = "device_not_found"
    DEVICE_UNAVAILABLE = "device_unavailable"
    PERMISSION_DENIED = "permission_denied"
    STREAM_FAILED = "stream_failed"
    INPUT_OVERFLOW = "input_overflow"
    NO_AUDIO = "no_audio"
    CANCELLED = "cancelled"
    BUSY = "busy"
    INVALID_DURATION = "invalid_duration"
    PERSISTENCE_DISABLED = "persistence_disabled"
    INVALID_DESTINATION = "invalid_destination"
    FILE_EXISTS = "file_exists"
    EXPORT_FAILED = "export_failed"


class RecordingState(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AudioFormat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sample_rate: int = Field(default=16000, ge=8000, le=48000, strict=True)
    channels: Literal[1, 2] = 1
    dtype: Literal["int16"] = "int16"

    @field_validator("channels", mode="before")
    @classmethod
    def validate_channels(cls, value):
        if type(value) is not int:
            raise ValueError("Channels must be an integer")
        return value


class InputDevice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0, strict=True)
    name: str = Field(min_length=1, repr=False)
    max_input_channels: int = Field(ge=1, strict=True)
    default_sample_rate: float = Field(gt=0, allow_inf_nan=False)


class RecordedAudio(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")
    format: AudioFormat
    samples: np.ndarray = Field(repr=False)

    @model_validator(mode="after")
    def validate_samples(self):
        if (self.samples.dtype != np.dtype("int16") or self.samples.ndim != 2
                or self.samples.shape[1] != self.format.channels
                or not 0 < len(self.samples) <= self.format.sample_rate * 120):
            raise ValueError("Invalid PCM sample format or length")
        samples = self.samples.copy(order="C")
        samples.flags.writeable = False
        object.__setattr__(self, "samples", samples)
        return self

    @property
    def duration(self) -> float:
        return len(self.samples) / self.format.sample_rate


class RecordingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    format: AudioFormat
    audio: RecordedAudio | None = Field(default=None, repr=False)
    started_at: datetime
    ended_at: datetime
    device: InputDevice | None = None
    status: Literal["succeeded", "cancelled", "failed"]
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if (self.started_at.utcoffset() is None or self.ended_at.utcoffset() is None
                or self.ended_at < self.started_at):
            raise ValueError("Invalid recording timestamps")
        if self.status == "succeeded":
            if self.audio is None or self.device is None or self.error_code is not None:
                raise ValueError("Successful capture requires audio and device")
            if self.audio.format != self.format:
                raise ValueError("Audio formats differ")
        elif self.audio is not None or self.error_code is None:
            raise ValueError("Unsuccessful capture must discard audio and include a code")
        if self.status == "cancelled" and self.error_code != ErrorCode.CANCELLED:
            raise ValueError("Cancellation requires the cancellation code")
        return self

    @property
    def samples(self) -> np.ndarray | None:
        return self.audio.samples if self.audio is not None else None

    @property
    def sample_rate(self) -> int:
        return self.format.sample_rate

    @property
    def channels(self) -> int:
        return self.format.channels

    @property
    def duration(self) -> float:
        return self.audio.duration if self.audio is not None else 0.0
