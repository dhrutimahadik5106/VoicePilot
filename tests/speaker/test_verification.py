from threading import Event
from uuid import uuid4
import numpy as np
import pytest
from app.speaker.verification import VerificationService
from tests.speaker.conftest import MemoryStore

@pytest.mark.parametrize("score,status",[(1,"verified"),(.6,"uncertain"),(.2,"rejected")])
def test_decisions(engine,quality,profile,policy,audio,score,status):
    engine.extract=lambda *a,**kw: [score,np.sqrt(1-score**2),0]
    r=VerificationService(engine,quality,MemoryStore(profile),policy).verify(audio(),profile.profile_id,audio_id=uuid4())
    assert r.status==status and r.similarity==pytest.approx(score)
    assert r.spoof_assurance=="not_assessed"

@pytest.mark.parametrize("case,status", [("missing","invalid_profile"),("model","unavailable"),
    ("badvector","invalid_audio"),("exception","unavailable"),("mismatch","invalid_profile"),
    ("pending","unavailable"),("cancel","cancelled"),("bad_audio","invalid_audio")])
def test_failures(engine,quality,profile,policy,audio,case,status):
    store=MemoryStore(profile)
    event=Event()
    if case=="missing": store.values.clear()
    if case=="model": engine.identity=None
    if case=="badvector": engine.extract=lambda *a,**kw: [0,0,0]
    if case=="exception":
        def fail(*a,**kw): raise RuntimeError("PRIVATE")
        engine.extract=fail
    if case=="mismatch": engine.identity=engine.identity.model_copy(update={"revision":"v2"})
    if case=="pending":
        policy.configuration=policy.configuration.model_copy(update={"calibration":"pending"})
        store.values[profile.profile_id]=profile.model_copy(update={"calibration":"pending"})
    if case=="cancel": event.set()
    r=VerificationService(engine,quality,store,policy).verify(None if case=="bad_audio" else audio(),
        profile.profile_id,audio_id=uuid4(),cancel=event)
    assert r.status==status
    assert "PRIVATE" not in r.model_dump_json()+repr(r)
