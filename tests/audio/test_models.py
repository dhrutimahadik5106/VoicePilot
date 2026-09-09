from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.audio.models import AudioFormat, InputDevice, RecordedAudio, RecordingResult


@pytest.mark.parametrize("field,value", [
    ("audio_channels", True), ("audio_max_duration_seconds", True),
    ("audio_input_device", 1.5), ("audio_sample_rate", 0), ("audio_sample_rate", 48001),
    ("audio_channels", 0), ("audio_channels", 3),
    ("audio_dtype", "float32"), ("audio_block_size", 0),
    ("audio_block_size", 4097), ("audio_max_duration_seconds", 0),
    ("audio_max_duration_seconds", 121), ("audio_max_duration_seconds", float("nan")),
    ("audio_max_duration_seconds", float("inf")), ("audio_input_device", -1),
    ("audio_input_device", ""), ("audio_input_device", "  "),
    ("audio_input_device", True), ("recordings_dir", "../private"),
    ("recordings_dir", "C:/private"), ("recordings_dir", "recordings/../private"),
    ("recordings_dir", "recordings/CON"), ("recordings_dir", "recordings/x:ads"),
])
def test_invalid_audio_config(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_audio_defaults_and_overrides(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert (settings.audio_sample_rate, settings.audio_channels, settings.audio_dtype) == (16000, 1, "int16")
    assert settings.recordings_dir == Path("recordings")
    assert settings.recording_persistence_enabled is False
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setenv("VOICEPILOT_AUDIO_INPUT_DEVICE", "2")
    monkeypatch.setenv("VOICEPILOT_AUDIO_SAMPLE_RATE", "48000")
    monkeypatch.setenv("VOICEPILOT_RECORDING_PERSISTENCE_ENABLED", "true")
    settings = Settings()
    assert settings.audio_input_device == 2
    assert settings.audio_sample_rate == 48000
    assert settings.recording_persistence_enabled is True


@pytest.mark.parametrize("samples", [
    np.zeros((2, 1), dtype=np.float32), np.zeros(2, dtype=np.int16),
    np.zeros((2, 2), dtype=np.int16), np.zeros((0, 1), dtype=np.int16),
    np.zeros((16000 * 120 + 1, 1), dtype=np.int16),
])
def test_invalid_samples(samples):
    with pytest.raises(ValidationError):
        RecordedAudio(format=AudioFormat(), samples=samples)


@pytest.mark.parametrize("kwargs", [
    {"sample_rate": 7999}, {"sample_rate": 48001}, {"channels": 3}, {"dtype": "float32"},
])
def test_invalid_format(kwargs):
    with pytest.raises(ValidationError):
        AudioFormat(**kwargs)


def test_samples_are_owned_and_readonly():
    samples = np.ones((160, 1), dtype=np.int16)
    audio = RecordedAudio(format=AudioFormat(), samples=samples)
    samples[:] = 0
    assert audio.samples.sum() == 160
    assert audio.duration == .01
    assert "samples" not in repr(audio)
    with pytest.raises(ValueError):
        audio.samples[0] = 2


def test_result_validation():
    now = datetime.now(timezone.utc)
    device = InputDevice(index=0, name="fake", max_input_channels=1, default_sample_rate=16000)
    audio = RecordedAudio(format=AudioFormat(), samples=np.zeros((160, 1), dtype=np.int16))
    result = RecordingResult(format=audio.format, audio=audio, device=device,
                             started_at=now, ended_at=now, status="succeeded")
    assert result.samples is audio.samples
    assert (result.sample_rate, result.channels, result.duration) == (16000, 1, .01)
    for changes in [
        {"ended_at": now - timedelta(seconds=1)}, {"started_at": datetime.now()},
        {"audio": None}, {"device": None}, {"status": "failed"},
        {"format": AudioFormat(channels=2)},
    ]:
        values = dict(format=audio.format, audio=audio, device=device,
                      started_at=now, ended_at=now, status="succeeded")
        with pytest.raises(ValidationError):
            RecordingResult(**(values | changes))

def test_all_audio_environment_overrides(monkeypatch):
    values = {
        "AUDIO_SAMPLE_RATE": "24000", "AUDIO_CHANNELS": "2",
        "AUDIO_DTYPE": "int16", "AUDIO_BLOCK_SIZE": "512",
        "AUDIO_MAX_DURATION_SECONDS": "4", "AUDIO_INPUT_DEVICE": "fake",
        "RECORDINGS_DIR": "recordings/test", "RECORDING_PERSISTENCE_ENABLED": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv("VOICEPILOT_" + key, value)
    settings = Settings()
    assert (settings.audio_sample_rate, settings.audio_channels, settings.audio_dtype) == (24000, 2, "int16")
    assert settings.audio_block_size == 512
    assert settings.audio_max_duration_seconds == 4
    assert settings.audio_input_device == "fake"
    assert settings.recordings_dir == Path("recordings/test")
    assert settings.recording_persistence_enabled
