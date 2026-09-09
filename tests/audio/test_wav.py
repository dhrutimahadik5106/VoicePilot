import wave
from pathlib import Path

import numpy as np
import pytest

from app.audio.contracts import AudioError
from app.audio.models import AudioFormat, RecordedAudio
from app.audio.wav import save_wav


def audio(channels=1):
    return RecordedAudio(format=AudioFormat(channels=channels),
                         samples=np.arange(160 * channels, dtype=np.int16).reshape(160, channels))


@pytest.mark.parametrize("channels", [1, 2])
def test_pcm_header_and_samples(tmp_path, monkeypatch, channels):
    monkeypatch.chdir(tmp_path)
    sample = audio(channels)
    target = save_wav(sample, persistence_enabled=True)
    assert target.parent == tmp_path / "recordings"
    assert ":" not in target.name
    with wave.open(str(target), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (channels, 2, 16000, 160)
        assert wav.getcomptype() == "NONE"
        assert wav.readframes(160) == sample.samples.astype("<i2").tobytes()


def test_disabled_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AudioError, match="persistence_disabled"):
        save_wav(audio())
    assert list(tmp_path.iterdir()) == []


def test_no_overwrite_and_explicit_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = save_wav(audio(), filename="test.wav", persistence_enabled=True)
    before = target.read_bytes()
    with pytest.raises(AudioError, match="file_exists"):
        save_wav(audio(2), filename="test.wav", persistence_enabled=True)
    assert target.read_bytes() == before
    save_wav(audio(2), filename="test.wav", persistence_enabled=True, overwrite=True)
    with wave.open(str(target)) as wav:
        assert wav.getnchannels() == 2


@pytest.mark.parametrize("filename", ["../outside.wav", "C:/test.wav", "x.wav:ads", "CON.wav", "test.txt", "/test.wav"])
def test_invalid_filename_no_writes(tmp_path, monkeypatch, filename):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AudioError, match="invalid_destination"):
        save_wav(audio(), filename=filename, persistence_enabled=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("directory", ["../outside", "/outside", "data", "recordings/../outside"])
def test_invalid_directory_no_writes(tmp_path, monkeypatch, directory):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AudioError, match="invalid_destination"):
        save_wav(audio(), Path(directory), persistence_enabled=True)
    assert list(tmp_path.iterdir()) == []


def test_linked_directory_rejected_without_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "recordings")
    with pytest.raises(AudioError, match="invalid_destination"):
        save_wav(audio(), persistence_enabled=True)
    assert list(tmp_path.iterdir()) == []
