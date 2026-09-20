"""Validated configuration without filesystem or integration side effects."""
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.speaker.models import SpeakerConfiguration
from app.planning.models import Configuration as PlanningConfiguration
from app.execution.models import Configuration as ExecutionConfiguration
from app.launch.models import Configuration as LaunchConfiguration
from app.operations.models import Configuration as OperationsConfiguration
from app.owner.models import Configuration as OwnerConfiguration


def validate_recordings_dir(value) -> Path:
    """Lexical-only validation; do not touch the filesystem during settings load."""
    text = str(value).replace("\\", "/")
    parts = text.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL",
                *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}
    if (not parts or parts[0] != "recordings"
            or any(not part or part in {".", ".."}
                   or part.endswith((".", " "))
                   or part.split(".")[0].upper() in reserved
                   or any(char in '<>:"|?*' or ord(char) < 32 for char in part)
                   for part in parts)):
        raise ValueError("Recording directory must be within recordings")
    return Path(*parts)



def normalize_stt_language(value) -> str | None:
    """Normalize a language code; actual model support is checked at transcription."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid language code")
    value = value.strip().lower()
    if value == "auto":
        return None
    if not re.fullmatch(r"[a-z]{2,3}", value):
        raise ValueError("Invalid language code")
    return value


class Settings(BaseSettings):
    """Load VOICEPILOT_ environment variables; .env loading is deliberately opt-in."""

    model_config = SettingsConfigDict(env_prefix="VOICEPILOT_", extra="forbid", env_nested_delimiter="__")

    app_name: str = "VoicePilot"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: Path = Path("data")
    log_dir: Path = Path("logs")
    llm_provider: Literal["disabled", "ollama"] = "disabled"
    ollama_base_url: str = "http://localhost:11434"
    wake_word_enabled: bool = False
    speaker_verification_enabled: bool = False
    speaker: SpeakerConfiguration = Field(default_factory=SpeakerConfiguration)
    planning: PlanningConfiguration = Field(default_factory=PlanningConfiguration)
    execution: ExecutionConfiguration = Field(default_factory=ExecutionConfiguration)
    launch: LaunchConfiguration = Field(default_factory=LaunchConfiguration)
    operations: OperationsConfiguration = Field(default_factory=OperationsConfiguration)
    owner: OwnerConfiguration = Field(default_factory=OwnerConfiguration)
    whisper_model: Literal["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "turbo", "distil-small.en", "distil-medium.en", "distil-large-v2", "distil-large-v3", "distil-large-v3.5"] = "small"
    whisper_device: Literal["cpu", "cuda"] = "cpu"
    whisper_compute_type: Literal["int8", "float32", "float16", "int8_float16", "int8_float32"] = "int8"
    max_plan_steps: int = Field(default=10, ge=1, le=100)
    max_retries: int = Field(default=2, ge=0, le=10)
    task_timeout_seconds: float = Field(default=60.0, gt=0, le=3600, allow_inf_nan=False)

    audio_sample_rate: int = Field(default=16000, ge=8000, le=48000)
    audio_channels: Literal[1, 2] = 1
    audio_dtype: Literal["int16"] = "int16"
    audio_block_size: int = Field(default=1024, ge=64, le=4096)
    audio_max_duration_seconds: float = Field(default=120.0, ge=0.1, le=120, allow_inf_nan=False)
    audio_input_device: int | str | None = None
    recordings_dir: Path = Path("recordings")
    recording_persistence_enabled: bool = False

    @field_validator("audio_sample_rate", "audio_channels", "audio_block_size",
                     "audio_max_duration_seconds", mode="before")
    @classmethod
    def validate_audio_number(cls, value):
        if isinstance(value, bool):
            raise ValueError("Audio limits must be numeric")
        return value

    @field_validator("audio_channels", mode="before")
    @classmethod
    def parse_channels(cls, value):
        if isinstance(value, str) and value in {"1", "2"}:
            return int(value)
        return value

    @field_validator("audio_input_device", mode="before")
    @classmethod
    def validate_device(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError("Invalid input device")
        if isinstance(value, str):
            value = value.strip()
            if value == "default":
                return None
            if not value or any(ord(char) < 32 for char in value):
                raise ValueError("Invalid input device")
            if value.lstrip("-").isdigit():
                value = int(value)
        if isinstance(value, int) and value < 0:
            raise ValueError("Invalid input device")
        return value

    @field_validator("recordings_dir", mode="before")
    @classmethod
    def validate_recording_directory(cls, value):
        return validate_recordings_dir(value)


    stt_contextual_enabled: bool = False
    stt_language: str | None = None
    stt_vad_filter: bool = True
    stt_word_timestamps: bool = False
    stt_beam_size: int = Field(default=5, ge=1, le=10)
    stt_max_duration_seconds: float = Field(default=120.0, ge=0.1, le=120, allow_inf_nan=False)
    stt_model_dir: Path = Path("models/whisper")
    stt_local_files_only: bool = False

    # Unvalidated engineering defaults; these do not estimate STT confidence.
    stt_safety_word_repetitions: int = Field(default=8, ge=2, le=100)
    stt_safety_phrase_repetitions: int = Field(default=4, ge=2, le=100)
    stt_safety_phrase_min_tokens: int = Field(default=16, ge=4, le=800)
    stt_safety_min_tokens: int = Field(default=30, ge=1, le=1000)
    stt_safety_tokens_per_second: float = Field(default=6, gt=0, le=100, allow_inf_nan=False)
    stt_safety_min_characters: int = Field(default=180, ge=1, le=8192)
    stt_safety_characters_per_second: float = Field(default=40, gt=0, le=1000, allow_inf_nan=False)
    stt_safety_no_speech_prob: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    stt_safety_avg_logprob: float = Field(default=-1.0, le=0, allow_inf_nan=False)
    stt_safety_max_segments: int = Field(default=256, ge=1, le=4096)
    stt_safety_max_output_characters: int = Field(default=8192, ge=180, le=65536)

    @field_validator("stt_language", mode="before")
    @classmethod
    def validate_stt_language(cls, value):
        return normalize_stt_language(value)

    @field_validator("stt_beam_size", "stt_max_duration_seconds", mode="before")
    @classmethod
    def validate_stt_number(cls, value):
        if isinstance(value, bool):
            raise ValueError("STT limits must be numeric")
        return value

    @field_validator("stt_model_dir", mode="before")
    @classmethod
    def validate_model_directory(cls, value):
        text = str(value).replace("\\", "/")
        parts = text.split("/")
        if not parts or parts[0] != "models":
            raise ValueError("Model cache must be within models")
        # Reuse the lexical path policy without performing filesystem access.
        checked = validate_recordings_dir("/".join(["recordings", *parts[1:]]))
        return Path("models", *checked.parts[1:])


    audio_silence_stop_enabled: bool = False
    audio_silence_duration_seconds: float = Field(default=2.0, ge=0.25, le=30, allow_inf_nan=False)
    audio_silence_threshold: float = Field(default=0.01, gt=0, le=0.25, allow_inf_nan=False)
    stt_temperature: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    stt_vad_min_silence_duration_ms: int = Field(default=1000, ge=100, le=5000)
    stt_initial_prompt: str = Field(default="VoicePilot, Spotify, WhatsApp, Chrome, YouTube.", max_length=500, repr=False)
    stt_hotwords: str = Field(default="VoicePilot Spotify WhatsApp Chrome YouTube", max_length=300, repr=False)

    @field_validator("audio_silence_duration_seconds", "audio_silence_threshold",
                     "stt_temperature", "stt_vad_min_silence_duration_ms", mode="before")
    @classmethod
    def validate_refinement_number(cls, value):
        if isinstance(value, bool):
            raise ValueError("Numeric settings cannot be boolean")
        return value

    @field_validator("stt_initial_prompt", "stt_hotwords")
    @classmethod
    def validate_domain_text(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Vocabulary hints must contain printable text")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-cached settings; clear the cache to reload environment."""
    return Settings()
