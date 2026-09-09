"""Validated configuration without filesystem or integration side effects."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load VOICEPILOT_ environment variables; .env loading is deliberately opt-in."""

    model_config = SettingsConfigDict(env_prefix="VOICEPILOT_", extra="forbid")

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
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    max_plan_steps: int = Field(default=10, ge=1, le=100)
    max_retries: int = Field(default=2, ge=0, le=10)
    task_timeout_seconds: float = Field(default=60.0, gt=0, le=3600, allow_inf_nan=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-cached settings; clear the cache to reload environment."""
    return Settings()
