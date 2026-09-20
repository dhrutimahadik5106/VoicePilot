from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.owner.runtime import Runtime
from app.owner.models import OwnerError
from app.core.config import Settings


def test_expired_enter_wait_never_constructs_recorder(monkeypatch):
    import app.audio.recorder as recorder
    entered = [False]
    runtime = Runtime(Settings(), read=lambda _: entered.__setitem__(0, True) or "", write=lambda _: None)
    def guard():
        if entered[0]:
            raise OwnerError("authentication_expired")
    monkeypatch.setattr(recorder, "SoundDeviceRecorder", lambda *a, **k: pytest.fail("recorder_created"))
    with pytest.raises(OwnerError, match="authentication_expired"):
        runtime.capture(None, uuid4(), uuid4(), guard=guard)


def test_microphone_device_binding_without_real_capture(monkeypatch):
    import app.audio.recorder as recorder
    import app.audio.cli as audio_cli
    device = SimpleNamespace(index=1, name="synthetic-device", max_input_channels=1, default_sample_rate=16000)
    audio = object()
    configs = []
    class FakeRecorder:
        def __init__(self, settings):
            configs.append(settings)
        def record(self, *args, **kwargs):
            return SimpleNamespace(status="succeeded", device=device, audio=audio)
    monkeypatch.setattr(recorder, "SoundDeviceRecorder", FakeRecorder)
    monkeypatch.setattr(audio_cli, "terminal_control", lambda *a: None)
    runtime = Runtime(Settings(), read=lambda _: "", write=lambda _: None)
    session = uuid4()
    assert runtime.capture("synthetic", session, uuid4(), guard=lambda: None) is audio
    device.name = "other-synthetic-device"
    with pytest.raises(OwnerError, match="binding_mismatch"):
        runtime.capture(None, session, uuid4(), guard=lambda: None)
    assert configs[1].audio_input_device == 1


def test_vad_duration_gate():
    from app.owner.quality import check_speech_duration
    from app.owner.models import Configuration
    with pytest.raises(OwnerError, match="capture_quality_failed"):
        check_speech_duration(SimpleNamespace(safety_summary=SimpleNamespace(duration_after_vad=.2)), Configuration())
