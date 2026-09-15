from types import SimpleNamespace
from uuid import uuid4
import numpy as np
import pytest
from app.core.config import Settings
from app.speaker.interactive import LocalSpeakerSession
from app.speaker.models import SpeakerConfiguration
from app.speaker.contracts import SpeakerError
from tests.speaker.conftest import MemoryStore

def make(configuration,engine,profile,audio,answers):
    replies=iter(answers); output=[]
    engine.ready=lambda:None
    # Same real model checksum expected by ready; identity is injected synthetic.
    protector=SimpleNamespace(smoke=lambda:None)
    session=LocalSpeakerSession(Settings(speaker=configuration),read=lambda _:next(replies),write=output.append,
        engine=engine,protector=protector,control=lambda:None)
    session.recorder=SimpleNamespace(record=lambda *a,**kw:SimpleNamespace(status="succeeded",audio=audio()))
    store=MemoryStore(profile)
    session.repository=lambda **kw:store
    return session,store,output

@pytest.mark.parametrize("answers",[["no"],["yes","no"]])
def test_consent_no_capture(configuration,engine,profile,audio,answers):
    session,store,_=make(configuration,engine,profile,audio,answers)
    session.recorder.record=lambda *a,**kw:pytest.fail("capture_without_consent")
    with pytest.raises(SpeakerError,match="cancelled"):session.enroll()
    assert len(store.values)==1

def test_success_no_audio_persistence(configuration,engine,profile,audio):
    session,store,_=make(configuration,engine,profile,audio,["yes","yes","","","",""])
    result=session.enroll()
    assert result["status"]=="enrolled" and not result["raw_audio_saved"]
    assert len(store.values)==2
    saved=next(v for k,v in store.values.items() if k!=profile.profile_id)
    assert saved.enrollment_session and len(saved.enrollment_hashes)==4

def test_retry(configuration,engine,profile,audio):
    session,store,output=make(configuration,engine,profile,audio,["yes","yes","","","","",""])
    good=audio
    values=iter([None,good(),good(),good(),good()])
    session.recorder.record=lambda *a,**kw:SimpleNamespace(status="succeeded",audio=next(values))
    assert session.enroll()["status"]=="enrolled"
    assert "Unusable sample discarded." in output

def test_capture_cancel_preserves_old(configuration,engine,profile,audio):
    session,store,_=make(configuration,engine,profile,audio,["yes","yes","yes","cancel"])
    with pytest.raises(SpeakerError,match="cancelled"):session.enroll(profile.profile_id)
    assert store.load(profile.profile_id) is profile

def test_delete_confirmation(configuration,engine,profile,audio):
    session,store,_=make(configuration,engine,profile,audio,["no"])
    with pytest.raises(SpeakerError):session.delete(profile.profile_id)
    assert store.load(profile.profile_id) is profile

def test_pending_diagnostics_only(configuration,engine,profile,audio):
    session,_,output=make(configuration,engine,profile,audio,[""])
    result=session.verify(profile.profile_id,diagnostics=True)
    assert result["status"]=="unavailable" and result["reason"]=="calibration_pending"
    assert result["similarity_score"]==1
    assert "Voice verified." not in output

def test_disabled_command_no_capture(configuration,engine,profile,audio):
    session,_,_=make(configuration,engine,profile,audio,[])
    session.recorder.record=lambda *a,**kw:pytest.fail("capture_disabled")
    with pytest.raises(SpeakerError,match="unavailable"): session.verify(profile.profile_id,command=True)

def test_delete_success(configuration,engine,profile,audio):
    session,store,_=make(configuration,engine,profile,audio,["yes"])
    assert session.delete(profile.profile_id)["status"]=="deleted"
    assert not store.values
