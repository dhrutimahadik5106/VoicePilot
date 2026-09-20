from threading import Event
import numpy as np
from app.core.config import Settings
from app.execution import cancellation
from app.audio.models import RecordedAudio, AudioFormat
from app.audio.recorder import SoundDeviceRecorder
from app.stt.service import TranscriptionService
from tests.audio.test_recorder import FakeBackend as AudioBackend
from tests.pipeline.helpers import transcription


def test_nested_registration_remains_active():
    hub=cancellation.CancellationHub();event=Event()
    with hub.track(event):
        with hub.track(event):pass
        assert hub.cancel()==1 and event.is_set()
    assert hub.cancel()==0


def test_global_stop_blocks_capture_before_device_access(monkeypatch):
    hub=cancellation.CancellationHub();hub.cancel(emergency=True)
    monkeypatch.setattr(cancellation,'GLOBAL',hub)
    backend=AudioBackend()
    result=SoundDeviceRecorder(Settings(),backend=backend).record(.1)
    assert result.status=='cancelled' and not backend.calls


def test_global_cancel_discards_stt_result(monkeypatch):
    hub=cancellation.CancellationHub();monkeypatch.setattr(cancellation,'GLOBAL',hub)
    class Engine:
        def transcribe(self,request,cancel=None):
            assert hub.cancel()==1
            return transcription(request.audio_id)
    audio=RecordedAudio(format=AudioFormat(sample_rate=16000),samples=np.ones((16000,1),dtype=np.int16))
    result=TranscriptionService(Settings(),Engine()).transcribe_audio(audio)
    assert result.status=='cancelled' and result.raw_transcript==''


def test_global_stop_blocks_stt_engine(monkeypatch):
    hub=cancellation.CancellationHub();hub.cancel(emergency=True)
    monkeypatch.setattr(cancellation,'GLOBAL',hub)
    class Engine:
        def transcribe(self,*a,**k):raise AssertionError('engine_called')
    audio=RecordedAudio(format=AudioFormat(sample_rate=16000),samples=np.ones((16000,1),dtype=np.int16))
    assert TranscriptionService(Settings(),Engine()).transcribe_audio(audio).status=='cancelled'



def test_global_cancel_signals_original_caller_event():
    hub = cancellation.CancellationHub()
    caller = Event()
    signal = cancellation.CombinedSignal(caller)
    with hub.track(signal):
        hub.cancel()
    assert caller.is_set() and signal.is_set()
