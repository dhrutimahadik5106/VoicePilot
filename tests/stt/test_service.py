import wave
from pathlib import Path
from threading import Event
from uuid import uuid4

import numpy as np
import pytest

from app.core.config import Settings
from app.stt.contracts import TranscriptionError
from app.stt.models import TranscriptionErrorCode as Code
from app.stt.service import TranscriptionService, read_pcm_wav
from tests.stt import FakeEngine, audio, isolated_stt


def make_wav(path, *, rate=16000, channels=1, width=2, frames=1600, payload=None):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(payload if payload is not None else bytes(frames * channels * width))
    return path


def test_service_audio_identity_and_language_override():
    engine = FakeEngine()
    service = TranscriptionService(Settings(stt_language="hi"), engine)
    identifier, correlation = uuid4(), uuid4()
    result = service.transcribe_audio(audio(), audio_id=identifier, execution_correlation_id=correlation)
    assert result.audio_id == identifier and result.execution_correlation_id == correlation
    assert engine.requests[-1].language == "hi"
    service.transcribe_audio(audio(), language="auto")
    assert engine.requests[-1].language is None


def test_missing_corrupt_empty_and_long_files(tmp_path):
    engine = FakeEngine()
    service = TranscriptionService(Settings(stt_max_duration_seconds=.5), engine)
    assert service.transcribe_file(tmp_path / "missing.wav").error_code == Code.FILE_NOT_FOUND
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"not a wav")
    assert service.transcribe_file(corrupt).error_code == Code.INVALID_WAV
    assert service.transcribe_file(make_wav(tmp_path / "empty.wav", frames=0)).error_code == Code.EMPTY_AUDIO
    assert service.transcribe_file(make_wav(tmp_path / "long.wav", frames=16000)).error_code == Code.AUDIO_TOO_LONG
    assert engine.requests == []


@pytest.mark.parametrize("width,value,expected", [
    (1, bytes([255, 0]), [32512, -32768]),
    (2, np.array([32767, -32768], dtype="<i2").tobytes(), [32767, -32768]),
    (3, bytes([255, 255, 127, 0, 0, 128]), [32767, -32768]),
    (4, np.array([2147483647, -2147483648], dtype="<i4").tobytes(), [32767, -32768]),
])
def test_pcm_widths(tmp_path, width, value, expected):
    path = make_wav(tmp_path / "sample.wav", width=width, payload=value)
    converted = read_pcm_wav(path, 120)
    assert converted.samples[:, 0].tolist() == expected


@pytest.mark.parametrize("rate", [8000, 16000, 22050, 44100, 48000])
def test_supported_rates_and_multichannel_conversion(tmp_path, rate):
    payload = np.tile(np.array([1000, -1000, 2000, -2000], dtype="<i2"), 100).tobytes()
    converted = read_pcm_wav(make_wav(tmp_path / "multi.wav", rate=rate, channels=4, payload=payload), 120)
    assert converted.format.sample_rate == rate and converted.format.channels == 1
    assert np.all(converted.samples == 0)


def test_truncated_file_rejected(tmp_path):
    path = make_wav(tmp_path / "cut.wav")
    path.write_bytes(path.read_bytes()[:-2])
    with pytest.raises(TranscriptionError, match="invalid_wav"):
        read_pcm_wav(path, 120)


@pytest.mark.parametrize("kwargs", [{"rate": 96000}, {"channels": 9}])
def test_unsupported_wav(tmp_path, kwargs):
    with pytest.raises(TranscriptionError, match="unsupported_audio"):
        read_pcm_wav(make_wav(tmp_path / "unsupported.wav", **kwargs), 120)


def test_permission_error_is_safe(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise PermissionError("sensitive path")
    monkeypatch.setattr(Path, "stat", denied)
    result = TranscriptionService(Settings(), FakeEngine()).transcribe_file(tmp_path / "private.wav")
    assert result.error_code == Code.PERMISSION_DENIED
    assert "sensitive" not in repr(result)


def test_cancelled_file_does_not_read_and_audio_limit(monkeypatch):
    engine = FakeEngine()
    service = TranscriptionService(Settings(stt_max_duration_seconds=.5), engine)
    cancel = Event()
    cancel.set()
    result = service.transcribe_file(Path("never-read.wav"), cancel=cancel)
    assert result.error_code == Code.CANCELLED
    assert service.transcribe_audio(audio()).error_code == Code.AUDIO_TOO_LONG
    assert engine.requests == []
