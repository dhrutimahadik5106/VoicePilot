from types import SimpleNamespace
from threading import Event
import numpy as np
import pytest
from app.speaker.sherpa_backend import SherpaEmbeddingEngine
from app.speaker.models import SpeakerConfiguration
from app.speaker.contracts import SpeakerError
from app.stt.audio_preprocessing import prepare_audio

def make(output=None):
    samples=[]
    stream=SimpleNamespace(accept_waveform=lambda **kw:samples.append(kw),input_finished=lambda:None)
    extractor=SimpleNamespace(dim=256,create_stream=lambda:stream,is_ready=lambda _:True,
        compute=lambda _:np.ones(256) if output is None else output)
    calls=[]
    engine=SherpaEmbeddingEngine("fake.onnx",SpeakerConfiguration(min_duration=.1),
        factory=lambda p:(calls.append(p) or extractor),inspector=lambda _:None)
    return engine,samples,calls,extractor

def test_lazy_and_preprocessing(audio):
    engine,samples,calls,_=make()
    assert calls==[]
    a=audio()
    vector=engine.extract(a)
    engine.extract(a)
    assert len(calls)==1 and np.isclose(np.linalg.norm(vector),1)
    actual=samples[0]["waveform"]
    assert samples[0]["sample_rate"]==16000
    assert actual.dtype==np.float32 and actual.flags.c_contiguous
    assert np.array_equal(actual,prepare_audio(a,decoder=None,max_duration=30))

@pytest.mark.parametrize("output",[[],np.zeros(256),np.ones(255),np.full(256,np.nan),np.full(256,np.inf),np.ones((1,256))])
def test_bad_output(audio,output):
    engine,*_=make(output)
    with pytest.raises(SpeakerError): engine.extract(audio())

def test_quality_before_load():
    engine,_,calls,_=make()
    with pytest.raises(SpeakerError,match="invalid_audio"): engine.extract(None)
    assert calls==[]

def test_cancel(audio):
    engine,_,calls,_=make()
    event=Event(); event.set()
    with pytest.raises(SpeakerError,match="cancelled"): engine.extract(audio(),cancel=event)
    assert calls==[]

def test_failure_private(audio,capsys,caplog):
    engine,_,_,extractor=make()
    def fail(_): raise RuntimeError("PRIVATE_EMBEDDING")
    extractor.compute=fail
    with pytest.raises(SpeakerError,match="inference_failed") as e: engine.extract(audio())
    assert "PRIVATE" not in str(e.value)+capsys.readouterr().out+caplog.text

def test_missing_model(audio):
    engine,*_=make()
    def fail(_): raise SpeakerError("model_missing")
    engine.inspector=fail
    with pytest.raises(SpeakerError,match="model_missing"): engine.extract(audio())
