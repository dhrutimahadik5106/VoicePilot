from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.stt.models import (
    SafeTranscriptionError, TranscriptSegment, TranscriptionErrorCode as Code,
    TranscriptionRequest, TranscriptionResult, TranscriptionStatus, WordTimestamp,
)
from tests.stt import audio, isolated_stt


@pytest.mark.parametrize("field,value", [
    ("stt_beam_size", 0), ("stt_beam_size", 11), ("stt_beam_size", True),
    ("stt_max_duration_seconds", 0), ("stt_max_duration_seconds", 121),
    ("stt_max_duration_seconds", float("inf")), ("stt_max_duration_seconds", float("nan")),
    ("stt_language", ""), ("stt_language", "English"), ("stt_language", 1),
    ("stt_model_dir", "../models"), ("stt_model_dir", "models/../private"),
    ("stt_model_dir", "C:/models"), ("whisper_model", "../private"),
    ("whisper_device", "invalid"), ("whisper_compute_type", "invalid"),
])
def test_configuration_validation(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_configuration_defaults_overrides_and_no_writes(monkeypatch, tmp_path):
    settings = Settings()
    assert (settings.whisper_model, settings.whisper_device, settings.whisper_compute_type) == ("base", "cpu", "int8")
    assert settings.stt_language is None
    assert settings.stt_vad_filter and not settings.stt_word_timestamps
    assert settings.stt_max_duration_seconds == 120
    assert settings.stt_beam_size == 5 and not settings.stt_local_files_only
    values = {
        "STT_LANGUAGE": "HI", "STT_VAD_FILTER": "false", "STT_WORD_TIMESTAMPS": "true",
        "STT_MAX_DURATION_SECONDS": "10", "STT_BEAM_SIZE": "2",
        "STT_LOCAL_FILES_ONLY": "true", "STT_MODEL_DIR": "models/test",
        "WHISPER_MODEL": "small", "WHISPER_DEVICE": "cuda", "WHISPER_COMPUTE_TYPE": "float16",
    }
    for key, value in values.items():
        monkeypatch.setenv("VOICEPILOT_" + key, value)
    settings = Settings()
    assert settings.stt_language == "hi"
    assert not settings.stt_vad_filter and settings.stt_word_timestamps
    assert settings.stt_max_duration_seconds == 10 and settings.stt_beam_size == 2
    assert settings.stt_local_files_only
    assert str(settings.stt_model_dir).replace("\\", "/") == "models/test"
    assert (settings.whisper_model, settings.whisper_device, settings.whisper_compute_type) == ("small", "cuda", "float16")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("values", [
    {"start": -1, "end": 1}, {"start": 2, "end": 1},
    {"start": 0, "end": float("nan")},
])
def test_invalid_segments(values):
    with pytest.raises(ValidationError):
        TranscriptSegment(text="private", **values)


def test_language_and_identifiers():
    correlation = uuid4()
    request = TranscriptionRequest(audio=audio(), language="HI", execution_correlation_id=correlation)
    assert request.language == "hi" and request.execution_correlation_id == correlation
    assert TranscriptionRequest(audio=audio(), language="auto").language is None
    with pytest.raises(ValidationError):
        TranscriptionRequest(audio=audio(), language="not-a-language")


def test_result_metrics_and_privacy():
    result = TranscriptionResult(
        audio_id=uuid4(), text="private words", language="en", language_probability=.8,
        segments=(TranscriptSegment(text=" private words ", start=0, end=1),),
        processing_duration=.5, source_audio_duration=1, model_name="base", device="cpu",
        compute_type="int8", status=TranscriptionStatus.SUCCEEDED,
    )
    assert result.real_time_factor == .5
    assert result.model_dump()["real_time_factor"] == .5
    assert "private words" not in repr(result)
    assert "confidence" not in result.model_dump()
    for changes in [
        {"language_probability": 1.1}, {"processing_duration": -1},
        {"timestamp": datetime.now()}, {"text": "mismatch"},
        {"status": TranscriptionStatus.FAILED},
    ]:
        with pytest.raises(ValidationError):
            TranscriptionResult(**(result.model_dump(exclude={"real_time_factor"}) | changes))


def test_failure_and_zero_duration_factor():
    result = TranscriptionResult(
        audio_id=uuid4(), processing_duration=0, source_audio_duration=0,
        model_name="base", device="cpu", compute_type="int8",
        status=TranscriptionStatus.FAILED, error=SafeTranscriptionError(code=Code.EMPTY_AUDIO),
    )
    assert result.real_time_factor is None and result.error_code == Code.EMPTY_AUDIO


def test_word_timestamp_validation():
    with pytest.raises(ValidationError):
        TranscriptSegment(text="one", start=0, end=1,
                          words=(WordTimestamp(text="one", start=0, end=2),))
