import importlib
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import (
    VoicePilotError, ConfigurationError, SecurityError,
    ToolExecutionError, VerificationError,
)
from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    import os
    for key in list(os.environ):
        if key.upper().startswith("VOICEPILOT_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_safe_defaults(tmp_path):
    settings = Settings()
    assert settings.model_dump() == {
        "app_name": "VoicePilot", "environment": "development", "debug": False,
        "log_level": "INFO", "data_dir": Path("data"), "log_dir": Path("logs"),
        "llm_provider": "disabled", "ollama_base_url": "http://localhost:11434",
        "wake_word_enabled": False, "speaker_verification_enabled": False,
        "whisper_model": "small", "whisper_device": "cpu",
        "whisper_compute_type": "int8", "max_plan_steps": 10,
        "max_retries": 2, "task_timeout_seconds": 60.0,
        "audio_sample_rate": 16000, "audio_channels": 1, "audio_dtype": "int16",
        "audio_block_size": 1024, "audio_max_duration_seconds": 120.0,
        "audio_input_device": None, "recordings_dir": Path("recordings"),
        "recording_persistence_enabled": False,
        "stt_language": None, "stt_vad_filter": True, "stt_word_timestamps": False,
        "stt_beam_size": 5, "stt_max_duration_seconds": 120.0,
        "stt_model_dir": Path("models/whisper"), "stt_local_files_only": False,
        "audio_silence_stop_enabled": False, "audio_silence_duration_seconds": 2.0,
        "audio_silence_threshold": 0.01, "stt_temperature": 0.0,
        "stt_vad_min_silence_duration_ms": 1000,
        "stt_initial_prompt": "VoicePilot, Spotify, WhatsApp, Chrome, YouTube, Dhruti.",
        "stt_safety_word_repetitions": 8, "stt_safety_phrase_repetitions": 4,
        "stt_safety_phrase_min_tokens": 16, "stt_safety_min_tokens": 30,
        "stt_safety_tokens_per_second": 6, "stt_safety_min_characters": 180,
        "stt_safety_characters_per_second": 40, "stt_safety_no_speech_prob": .8,
        "stt_safety_avg_logprob": -1.0, "stt_safety_max_segments": 256,
        "stt_safety_max_output_characters": 8192,
        "stt_hotwords": "VoicePilot Spotify WhatsApp Chrome YouTube Dhruti",
    }
    assert list(tmp_path.iterdir()) == []


def test_environment_overrides(monkeypatch):
    overrides = {
        "APP_NAME": "TestPilot", "ENVIRONMENT": "test", "DEBUG": "true",
        "LOG_LEVEL": "WARNING", "DATA_DIR": "test-data", "LOG_DIR": "test-logs",
        "LLM_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://localhost:1234",
        "WAKE_WORD_ENABLED": "true", "SPEAKER_VERIFICATION_ENABLED": "true",
        "WHISPER_MODEL": "tiny", "WHISPER_DEVICE": "cpu",
        "WHISPER_COMPUTE_TYPE": "float32", "MAX_PLAN_STEPS": "3",
        "MAX_RETRIES": "0", "TASK_TIMEOUT_SECONDS": "5",
    }
    for key, value in overrides.items():
        monkeypatch.setenv("VOICEPILOT_" + key, value)
    settings = Settings()
    for key, value in overrides.items():
        actual = getattr(settings, key.lower())
        if isinstance(actual, bool):
            assert actual is (value == "true")
        elif isinstance(actual, (int, float)):
            assert actual == float(value)
        else:
            assert str(actual) == value


@pytest.mark.parametrize("field,value", [
    ("max_plan_steps", 0), ("max_plan_steps", 101),
    ("max_retries", -1), ("max_retries", 11),
    ("task_timeout_seconds", 0), ("task_timeout_seconds", -1),
    ("task_timeout_seconds", 3601), ("task_timeout_seconds", float("inf")),
    ("task_timeout_seconds", float("nan")), ("max_plan_steps", "invalid"),
    ("max_retries", 1.5),
])
def test_invalid_numeric_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_invalid_environment_limit(monkeypatch):
    monkeypatch.setenv("VOICEPILOT_MAX_PLAN_STEPS", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_cached_accessor(monkeypatch):
    first = get_settings()
    monkeypatch.setenv("VOICEPILOT_APP_NAME", "Changed")
    assert get_settings() is first
    get_settings.cache_clear()
    assert get_settings().app_name == "Changed"


def test_exception_hierarchy():
    for error in (ConfigurationError, SecurityError, ToolExecutionError, VerificationError):
        assert issubclass(error, VoicePilotError)


def test_logging_no_duplicate_handlers_and_redaction(capsys):
    logger = logging.getLogger("voicepilot")
    old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = []
    try:
        assert configure_logging("INFO") is configure_logging("WARNING")
        assert len(logger.handlers) == 1
        assert logger.level == logging.WARNING
        logger.info("foundation_ready")
        assert capsys.readouterr().err == ""
        logger.warning("foundation_ready")
        assert capsys.readouterr().err == "30 foundation_ready\n"
        logger.error("credential=secret")
        logger.error("foundation_ready %s", "sensitive message")
        try:
            raise ValueError("sensitive file contents")
        except ValueError:
            logger.exception("shutdown", stack_info=True)
        output = capsys.readouterr().err
        assert output == "40 event_redacted\n40 event_redacted\n40 shutdown\n"
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate


@pytest.mark.parametrize("module", [
    "app", "app.core", "app.core.config", "app.core.errors", "app.core.logging",
])
def test_phase_one_imports(module):
    assert importlib.import_module(module)
