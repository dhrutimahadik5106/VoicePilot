import importlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.core.config import Settings
from app.audio.contracts import AudioError
from app.audio.models import ErrorCode, RecordingState
from app.audio.recorder import SoundDeviceRecorder


class FakeBackend:
    class CallbackStop(Exception):
        pass

    def __init__(self, frames=160, *, fail=None, overflow=False):
        self.frames = frames
        self.fail = fail
        self.overflow = overflow
        self.default = SimpleNamespace(device=(0, 0))
        self.calls = []
        self.options = None

    def query_devices(self):
        self.calls.append("query")
        return [dict(name="fake", max_input_channels=2, default_samplerate=16000)]

    def check_input_settings(self, **kwargs):
        self.calls.append("check")

    def RawInputStream(self, **kwargs):
        self.calls.append("construct")
        self.options = kwargs
        if self.fail == "construct":
            raise PermissionError("private device details")
        return self

    def start(self):
        self.calls.append("start")
        if self.fail == "start":
            raise RuntimeError("private stream details")
        if self.frames:
            data = np.ones((self.frames, self.options["channels"]), dtype=np.int16)
            try:
                self.options["callback"](data.tobytes(), self.frames, None, self.overflow)
            except self.CallbackStop:
                pass

    def abort(self):
        self.calls.append("abort")
        if self.fail == "abort":
            raise RuntimeError("private abort details")

    def close(self):
        self.calls.append("close")
        if self.fail == "close":
            raise RuntimeError("private close details")


def test_no_access_on_construction():
    backend = FakeBackend()
    recorder = SoundDeviceRecorder(Settings(), backend=backend)
    assert recorder.state == RecordingState.IDLE
    assert backend.calls == []


def test_stop_state_and_cleanup():
    backend = FakeBackend()
    recorder = SoundDeviceRecorder(Settings(), backend=backend)
    def control():
        assert recorder.state == RecordingState.RECORDING
        return "stop"
    result = recorder.record(3, control)
    assert result.status == "succeeded"
    assert result.duration == .01
    assert result.device.index == 0
    assert result.ended_at >= result.started_at
    assert recorder.state == RecordingState.SUCCEEDED
    assert backend.calls[-2:] == ["abort", "close"]


def test_frame_duration_limit():
    backend = FakeBackend(frames=5000)
    recorder = SoundDeviceRecorder(Settings(), backend=backend)
    result = recorder.record(.1)
    assert result.samples.shape == (1600, 1)
    assert result.duration == .1
    assert backend.calls[-2:] == ["abort", "close"]


def test_wall_clock_limit_without_callbacks():
    backend = FakeBackend(frames=0)
    ticks = iter([0, 4])
    result = SoundDeviceRecorder(Settings(), backend=backend, clock=lambda: next(ticks)).record(3)
    assert result.error_code == ErrorCode.NO_AUDIO
    assert backend.calls[-2:] == ["abort", "close"]


def test_cancel_discards_and_allows_reuse():
    backend = FakeBackend()
    recorder = SoundDeviceRecorder(Settings(), backend=backend)
    result = recorder.record(3, lambda: "cancel")
    assert result.status == "cancelled"
    assert result.samples is None and result.duration == 0
    assert result.error_code == ErrorCode.CANCELLED
    assert recorder.state == RecordingState.CANCELLED
    assert backend.calls[-2:] == ["abort", "close"]
    assert recorder.record(3, lambda: "stop").status == "succeeded"


@pytest.mark.parametrize("failure,code", [
    ("construct", ErrorCode.PERMISSION_DENIED),
    ("start", ErrorCode.STREAM_FAILED),
    ("abort", ErrorCode.STREAM_FAILED),
    ("close", ErrorCode.STREAM_FAILED),
])
def test_failure_cleanup(failure, code):
    backend = FakeBackend(fail=failure)
    result = SoundDeviceRecorder(Settings(), backend=backend).record(3, lambda: "stop")
    assert result.status == "failed"
    assert result.error_code == code
    assert result.audio is None
    assert "private" not in repr(result)
    if failure != "construct":
        assert backend.calls[-2:] == ["abort", "close"]


def test_overflow_discards_capture():
    backend = FakeBackend(overflow=True)
    result = SoundDeviceRecorder(Settings(), backend=backend).record(3)
    assert result.error_code == ErrorCode.INPUT_OVERFLOW
    assert result.audio is None
    assert backend.calls[-1] == "close"


def test_keyboard_interrupt_cancels():
    backend = FakeBackend()
    def control():
        raise KeyboardInterrupt
    result = SoundDeviceRecorder(Settings(), backend=backend).record(3, control)
    assert result.status == "cancelled"
    assert result.samples is None
    assert backend.calls[-1] == "close"


def test_busy_rejected_without_disturbing_capture():
    recorder = SoundDeviceRecorder(Settings(), backend=FakeBackend())
    def control():
        with pytest.raises(AudioError, match="busy"):
            recorder.record(1)
        return "stop"
    assert recorder.record(3, control).status == "succeeded"


@pytest.mark.parametrize("duration", [0, .001, -1, 121, float("nan"), float("inf"), True])
def test_invalid_duration_never_opens_device(duration):
    backend = FakeBackend()
    recorder = SoundDeviceRecorder(Settings(), backend=backend)
    with pytest.raises(AudioError, match="invalid_duration"):
        recorder.record(duration)
    assert backend.calls == []


def test_missing_device_result():
    backend = FakeBackend()
    backend.query_devices = lambda: []
    result = SoundDeviceRecorder(Settings(), backend=backend).record(1)
    assert result.error_code == ErrorCode.DEVICE_NOT_FOUND
    assert "construct" not in backend.calls


def test_imports_and_settings_never_load_backend(tmp_path):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import os
import sys
class BlockAudio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'sounddevice':
            raise AssertionError('Hardware backend imported')
sys.meta_path.insert(0, BlockAudio())
import app.audio, app.audio.models, app.audio.contracts
import app.audio.devices, app.audio.recorder, app.audio.wav, app.audio.cli
from app.core.config import Settings
os.chdir(sys.argv[1])
Settings()
assert not os.listdir('.')
assert 'sounddevice' not in sys.modules
"""
    completed = subprocess.run(
        [str(root / "venv" / "Scripts" / "python.exe"), "-B", "-c", script, str(tmp_path)],
        cwd=root, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr

def test_configured_stereo_and_maximum():
    backend = FakeBackend(frames=20000)
    settings = Settings(audio_sample_rate=8000, audio_channels=2,
                        audio_block_size=512, audio_max_duration_seconds=.5)
    result = SoundDeviceRecorder(settings, backend=backend).record()
    assert result.status == "succeeded"
    assert result.samples.shape == (4000, 2)
    assert result.duration == .5
    assert backend.options["samplerate"] == 8000
    assert backend.options["blocksize"] == 512
    assert backend.options["dtype"] == "int16"


def test_direct_cancel_and_stop_methods():
    recorder = SoundDeviceRecorder(Settings(), backend=FakeBackend())
    def cancel():
        recorder.cancel()
    assert recorder.record(1, cancel).status == "cancelled"
    def stop():
        recorder.stop()
    assert recorder.record(1, stop).status == "succeeded"


class ScriptedBackend(FakeBackend):
    """Deliver synthetic blocks without PortAudio or any actual device."""
    def __init__(self, levels):
        super().__init__(frames=0)
        self.levels = levels

    def start(self):
        self.calls.append("start")
        for level in self.levels:
            pcm = np.full((1600, self.options["channels"]), level, dtype=np.int16)
            try:
                self.options["callback"](pcm.tobytes(), 1600, None, False)
            except self.CallbackStop:
                break


def test_flexible_capture_until_terminal_enter(monkeypatch):
    import app.audio.cli as cli
    fake_keys = SimpleNamespace(kbhit=lambda: True, getwch=lambda: "\r")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_keys)
    monkeypatch.setattr(cli, "os", SimpleNamespace(name="nt"))
    backend = FakeBackend()
    result = SoundDeviceRecorder(Settings(), backend=backend).record(control=cli.terminal_control)
    assert result.status == "succeeded" and result.duration == .01
    assert backend.calls[-2:] == ["abort", "close"]


def test_flexible_safety_deadline():
    ticks = iter([0, 1])
    backend = FakeBackend()
    result = SoundDeviceRecorder(Settings(audio_max_duration_seconds=.5),
                                 backend=backend, clock=lambda: next(ticks)).record()
    assert result.status == "succeeded"
    assert backend.calls[-2:] == ["abort", "close"]


def test_flexible_safety_frame_limit():
    backend = FakeBackend(frames=32000)
    result = SoundDeviceRecorder(Settings(audio_max_duration_seconds=.5), backend=backend).record()
    assert result.duration == .5 and len(result.samples) == 8000


def test_optional_silence_stops_after_speech_and_retains_tail():
    settings = Settings(audio_silence_stop_enabled=True, audio_silence_duration_seconds=.25)
    backend = ScriptedBackend([1000, 0, 0, 0, 1000])
    result = SoundDeviceRecorder(settings, backend=backend).record()
    assert result.duration == .4
    assert len(result.samples) == 6400
    assert np.all(result.samples[-1600:] == 0)


def test_silence_disabled_preserves_pauses_and_final_words():
    backend = ScriptedBackend([1000, 0, 0, 0, 1000])
    result = SoundDeviceRecorder(Settings(), backend=backend).record(control=lambda: "stop")
    assert result.duration == .5
    assert np.all(result.samples[-1600:] == 1000)


def test_silence_resets_on_speech():
    settings = Settings(audio_silence_stop_enabled=True, audio_silence_duration_seconds=.25)
    result = SoundDeviceRecorder(settings, backend=ScriptedBackend(
        [1000, 0, 0, 1000, 0, 0, 0, 1000])).record()
    assert result.duration == .7


def test_initial_silence_waits_for_enter_or_safety():
    settings = Settings(audio_silence_stop_enabled=True, audio_silence_duration_seconds=.25)
    result = SoundDeviceRecorder(settings, backend=ScriptedBackend([0] * 5)).record(control=lambda: "stop")
    assert result.duration == .5


def test_flexible_cancel_discards_all_samples():
    result = SoundDeviceRecorder(Settings(), backend=FakeBackend()).record(control=lambda: "cancel")
    assert result.status == "cancelled" and result.samples is None
