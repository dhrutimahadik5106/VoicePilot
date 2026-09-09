from datetime import datetime, timezone

import pytest

from app.audio.models import AudioFormat, ErrorCode, InputDevice, RecordingResult
from app.core.config import Settings
from app.stt.cli import main
from tests.stt import FakeEngine, audio, isolated_stt
from tests.stt.test_service import make_wav


class FakeRecorder:
    def __init__(self, status="succeeded"):
        self.calls = []
        self.status = status

    def record(self, seconds, control=None):
        self.calls.append(seconds)
        now = datetime.now(timezone.utc)
        return RecordingResult(
            format=AudioFormat(), audio=audio() if self.status == "succeeded" else None,
            device=InputDevice(index=0, name="fake", max_input_channels=1, default_sample_rate=16000),
            started_at=now, ended_at=now, status=self.status,
            error_code=None if self.status == "succeeded" else
            ErrorCode.CANCELLED if self.status == "cancelled" else ErrorCode.STREAM_FAILED,
        )

    def cancel(self):
        self.calls.append("cancel")


def test_file_mode_with_fake_engine(tmp_path):
    path = make_wav(tmp_path / "chosen.wav")
    engine, output = FakeEngine(), []
    assert main(["file", str(path), "--language", "en"], settings=Settings(),
                engine=engine, write=output.append) == 0
    assert len(engine.requests) == 1
    assert "Transcript: hello" in output and "Language: en" in output
    assert any("processing:" in line and "RTF:" in line for line in output)
    assert any("download" in line for line in output)


def test_microphone_fake_capture_in_memory(tmp_path):
    engine, recorder, output = FakeEngine(), FakeRecorder(), []
    assert main(["microphone", "--seconds", "5"], engine=engine, recorder=recorder,
                settings=Settings(), read=lambda _: "", write=output.append) == 0
    assert recorder.calls == [5] and len(engine.requests) == 1
    assert any("RECORDING requested" in line for line in output)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status,exit_code", [("cancelled", 0), ("failed", 1)])
def test_capture_failure_or_cancel_does_not_transcribe(status, exit_code):
    engine = FakeEngine()
    assert main(["microphone"], settings=Settings(), engine=engine, recorder=FakeRecorder(status),
                read=lambda _: "", write=lambda _: None) == exit_code
    assert engine.requests == []


def test_cancel_before_capture():
    engine, recorder = FakeEngine(), FakeRecorder()
    assert main(["microphone"], settings=Settings(), engine=engine, recorder=recorder,
                read=lambda _: "c", write=lambda _: None) == 0
    assert engine.requests == [] and recorder.calls == []


@pytest.mark.parametrize("seconds", ["0", "-1", "nan", "121"])
def test_invalid_seconds_before_capture(seconds):
    recorder = FakeRecorder()
    assert main(["microphone", "--seconds", seconds], settings=Settings(),
                engine=FakeEngine(), recorder=recorder, write=lambda _: None) == 2
    assert recorder.calls == []


def test_file_missing_and_offline_notice():
    engine, output = FakeEngine(), []
    assert main(["file", "missing.wav"], settings=Settings(stt_local_files_only=True),
                engine=engine, write=output.append) == 1
    assert output == ["STT error: file_not_found"]
    assert engine.requests == []


def test_keyboard_interrupt_during_consent():
    def interrupted(_):
        raise KeyboardInterrupt
    engine, recorder = FakeEngine(), FakeRecorder()
    assert main(["microphone"], settings=Settings(), engine=engine, recorder=recorder,
                read=interrupted, write=lambda _: None) == 0
    assert engine.requests == []


def test_invalid_language_before_input():
    engine = FakeEngine()
    assert main(["microphone", "--language", "English"], settings=Settings(),
                engine=engine, write=lambda _: None) == 2
    assert engine.requests == []
