import numpy as np
import pytest
from app.audio.models import AudioFormat, RecordedAudio

def test_good(audio,quality):
    q=quality.assess(audio())
    assert q.eligible and q.duration==1 and q.sample_rate==16000

@pytest.mark.parametrize("value", [0,32767,-32768])
def test_bad_signal(value,quality):
    a=RecordedAudio(format=AudioFormat(),samples=np.full((16000,1),value,dtype=np.int16))
    assert not quality.assess(a).eligible

@pytest.mark.parametrize("rate", [8000,44100,48000])
def test_rate(rate,quality):
    a=RecordedAudio(format=AudioFormat(sample_rate=rate),samples=np.ones((rate,1),dtype=np.int16))
    assert not quality.assess(a).eligible

def test_short_and_long(audio,quality):
    a=audio()
    for pcm in [a.samples[:10],np.tile(a.samples,(3,1))]:
        assert not quality.assess(RecordedAudio(format=a.format,samples=pcm)).eligible

def test_cancelling_channels(audio,quality):
    a=audio()
    stereo=RecordedAudio(format=AudioFormat(channels=2),samples=np.concatenate([a.samples,-a.samples],axis=1))
    assert not quality.assess(stereo).eligible

@pytest.mark.parametrize("value",[None,object(),[],float("nan")])
def test_structure(value,quality):
    assert not quality.assess(value).eligible
