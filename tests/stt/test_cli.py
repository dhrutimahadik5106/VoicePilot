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


def test_default_capture_has_no_fixed_seconds_and_no_save(tmp_path):
    recorder, engine = FakeRecorder(), FakeEngine()
    assert main(["microphone"], settings=Settings(), engine=engine, recorder=recorder,
                read=lambda _: "", write=lambda _: None) == 0
    assert recorder.calls == [None]
    assert list(tmp_path.iterdir()) == []


def test_explicit_ten_second_capture():
    recorder = FakeRecorder()
    assert main(["microphone", "--seconds", "10"], settings=Settings(), engine=FakeEngine(),
                recorder=recorder, read=lambda _: "", write=lambda _: None) == 0
    assert recorder.calls == [10]


def test_session_reuses_model_for_consecutive_transcriptions(tmp_path):
    from app.stt.faster_whisper_engine import FasterWhisperEngine
    from tests.stt import FakeModel
    loads, output = [], []
    engine = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: loads.append(1) or FakeModel())
    answers = iter(["", "", "q"])
    recorder = FakeRecorder()
    assert main(["microphone", "--session"], settings=Settings(), engine=engine,
                recorder=recorder, read=lambda _: next(answers), write=output.append) == 0
    assert recorder.calls == [None, None] and loads == [1]
    assert sum("Start: cold" in line for line in output) == 1
    assert sum("Start: warm" in line for line in output) == 1
    assert list(tmp_path.iterdir()) == []
    engine.close()


def test_cli_preserves_final_sentence_words(tmp_path):
    from app.stt.faster_whisper_engine import FasterWhisperEngine
    from tests.stt import FakeModel, segment
    sentence = "Hey Voice Pilot open Spotify and please keep every final word"
    model = FakeModel([segment(" " + sentence, end=1)])
    engine = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: model)
    output = []
    assert main(["microphone"], settings=Settings(), engine=engine, recorder=FakeRecorder(),
                read=lambda _: "", write=output.append) == 0
    assert "Transcript: " + sentence in output
    assert list(tmp_path.iterdir()) == []


def test_elapsed_display_and_enter_control():
    class PollingRecorder(FakeRecorder):
        def record(self, seconds, control=None):
            assert control() == "stop"
            return super().record(seconds, control)
    ticks = iter([10, 12])
    output = []
    assert main(["microphone"], settings=Settings(), engine=FakeEngine(), recorder=PollingRecorder(),
                read=lambda _: "", write=output.append, control=lambda: "stop",
                clock=lambda: next(ticks)) == 0
    assert "Recording elapsed: 2s / 120s" in output


def test_silence_option_is_passed_to_owned_recorder(monkeypatch):
    import app.stt.cli as cli
    configured = []
    def factory(settings):
        configured.append(settings)
        return FakeRecorder()
    monkeypatch.setattr(cli, "SoundDeviceRecorder", factory)
    assert main(["microphone", "--silence-seconds", "3"], settings=Settings(),
                engine=FakeEngine(), read=lambda _: "", write=lambda _: None) == 0
    assert configured[0].audio_silence_stop_enabled
    assert configured[0].audio_silence_duration_seconds == 3


@pytest.mark.parametrize("value", ["0", "nan", "31"])
def test_invalid_silence_option_never_captures(value):
    recorder = FakeRecorder()
    assert main(["microphone", "--silence-seconds", value], settings=Settings(),
                engine=FakeEngine(), recorder=recorder, write=lambda _: None) == 2
    assert recorder.calls == []
