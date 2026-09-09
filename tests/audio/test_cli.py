from datetime import datetime, timezone

import numpy as np
import pytest

from app.core.config import Settings
from app.audio.cli import main
from app.audio.models import AudioFormat, ErrorCode, InputDevice, RecordedAudio, RecordingResult


class FakeRecorder:
    def __init__(self, status="succeeded"):
        self.calls = []
        now = datetime.now(timezone.utc)
        format = AudioFormat()
        self.result = RecordingResult(
            format=format, started_at=now, ended_at=now, status=status,
            device=InputDevice(index=0, name="fake", max_input_channels=1, default_sample_rate=16000),
            audio=RecordedAudio(format=format, samples=np.zeros((160, 1), dtype=np.int16)) if status == "succeeded" else None,
            error_code=None if status == "succeeded" else ErrorCode(status if status == "cancelled" else "stream_failed"),
        )

    def record(self, duration_seconds, control=None):
        self.calls.append(duration_seconds)
        return self.result

    def cancel(self):
        self.calls.append("cancel")


def test_listing_does_not_capture():
    fake = FakeRecorder()
    output = []
    assert main(["devices"], recorder=fake, device_lister=lambda: [fake.result.device], write=output.append) == 0
    assert fake.calls == []
    assert output == ["0: fake (1 input channels)"]


def test_explicit_start_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake, output = FakeRecorder(), []
    assert main(["record", "--seconds", "3"], recorder=fake, settings=Settings(),
                read=lambda _: "", write=output.append, control=lambda: "stop") == 0
    assert fake.calls == [3]
    assert any("RECORDING requested" in line for line in output)
    assert "RECORDING STOPPED." in output
    assert list(tmp_path.iterdir()) == []


def test_cancel_before_start():
    fake = FakeRecorder()
    assert main(["record"], recorder=fake, settings=Settings(), read=lambda _: "c", write=lambda _: None) == 0
    assert fake.calls == []


@pytest.mark.parametrize("status,exit_code", [("cancelled", 0), ("failed", 1)])
def test_unsuccessful_capture_never_saves(tmp_path, monkeypatch, status, exit_code):
    monkeypatch.chdir(tmp_path)
    fake = FakeRecorder(status)
    assert main(["record", "--save"], recorder=fake, settings=Settings(),
                read=lambda _: "", write=lambda _: None) == exit_code
    assert list(tmp_path.iterdir()) == []


def test_explicit_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["record", "--save", "--filename", "test.wav"], recorder=FakeRecorder(),
                settings=Settings(), read=lambda _: "", write=lambda _: None) == 0
    assert (tmp_path / "recordings" / "test.wav").exists()


def test_persistence_setting_alone_does_not_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["record"], recorder=FakeRecorder(),
                settings=Settings(recording_persistence_enabled=True),
                read=lambda _: "", write=lambda _: None) == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("seconds", ["0", "nan", "inf", "121"])
def test_invalid_duration_before_consent(seconds):
    fake = FakeRecorder()
    def unexpected(_):
        pytest.fail("Should validate before prompting")
    assert main(["record", "--seconds", seconds], recorder=fake, settings=Settings(),
                read=unexpected, write=lambda _: None) == 2
    assert fake.calls == []


def test_filename_requires_explicit_save():
    with pytest.raises(SystemExit) as error:
        main(["record", "--filename", "test.wav"])
    assert error.value.code == 2
