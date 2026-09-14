from threading import Event
from uuid import uuid4
import numpy as np
import pytest
from app.speaker.enrollment import EnrollmentService
from app.speaker.models import EnrollmentConsent
from tests.speaker.conftest import MemoryStore

def service(configuration,engine,quality,policy,store):
    return EnrollmentService(configuration,engine,quality,store,policy)

@pytest.mark.parametrize("consent,reason", [(EnrollmentConsent(),"consent_required"),
    (EnrollmentConsent(enrollment=True),"persistence_consent_required")])
def test_consent(configuration,engine,quality,policy,consent,reason):
    store=MemoryStore()
    r=service(configuration,engine,quality,policy,store).enroll(None,consent)
    assert r.reason==reason and not store.values

def test_success(configuration,engine,quality,policy,audio):
    store=MemoryStore()
    samples=[(uuid4(),audio()) for _ in range(4)]
    result=service(configuration,engine,quality,policy,store).enroll(samples,EnrollmentConsent(enrollment=True,persistence=True))
    assert result.status=="enrolled"
    assert np.linalg.norm(store.load(result.profile_id).template)==pytest.approx(1)
    assert "template" not in result.model_dump_json()

@pytest.mark.parametrize("count",[0,1,2,6])
def test_count(configuration,engine,quality,policy,audio,count):
    store=MemoryStore()
    result=service(configuration,engine,quality,policy,store).enroll([(uuid4(),audio()) for _ in range(count)],
        EnrollmentConsent(enrollment=True,persistence=True))
    assert result.reason=="sample_count" and not store.values

@pytest.mark.parametrize("vector",[[0,0,0],[1,0],[float("nan"),0,0],[-1,0,0]])
def test_bad_or_inconsistent_preserves_old(configuration,engine,quality,policy,audio,profile,vector):
    store=MemoryStore(profile)
    calls=iter([[1,0,0],vector,[1,0,0]])
    engine.extract=lambda *a,**kw: next(calls)
    r=service(configuration,engine,quality,policy,store).enroll([(uuid4(),audio()) for _ in range(3)],
        EnrollmentConsent(enrollment=True,persistence=True),profile_id=profile.profile_id)
    assert r.status!="enrolled" and store.load(profile.profile_id) is profile

@pytest.mark.parametrize("stage",["before","quality","embedding","save"])
def test_cancel_rollback(configuration,engine,quality,policy,audio,profile,stage):
    event=Event()
    store=MemoryStore(profile)
    if stage=="before": event.set()
    if stage=="quality":
        original=quality.assess
        def assess(a):
            event.set()
            return original(a)
        quality.assess=assess
    if stage=="embedding":
        def extract(*a,**kw):
            event.set()
            return [1,0,0]
        engine.extract=extract
    if stage=="save":
        original=store.save
        def save(p,**kw):
            event.set()
            original(p,**kw)
        store.save=save
    r=service(configuration,engine,quality,policy,store).enroll([(uuid4(),audio()) for _ in range(3)],
        EnrollmentConsent(enrollment=True,persistence=True),cancel=event,profile_id=profile.profile_id)
    assert r.status=="cancelled"
    assert store.load(profile.profile_id) is profile

def test_duplicate_capture(configuration,engine,quality,policy,audio):
    store=MemoryStore()
    a=audio()
    r=service(configuration,engine,quality,policy,store).enroll([(uuid4(),a) for _ in range(3)],
        EnrollmentConsent(enrollment=True,persistence=True))
    assert r.reason=="duplicate_sample"

def test_backend_safe(configuration,engine,quality,policy,audio,capsys,caplog):
    def fail(*a,**kw): raise RuntimeError("PRIVATE_VECTOR")
    engine.extract=fail
    r=service(configuration,engine,quality,policy,MemoryStore()).enroll([(uuid4(),audio()) for _ in range(3)],
        EnrollmentConsent(enrollment=True,persistence=True))
    assert r.status=="unavailable"
    assert "PRIVATE_VECTOR" not in repr(r)+r.model_dump_json()+capsys.readouterr().out+caplog.text

def test_average_is_equal_weight(configuration,engine,quality,policy,audio):
    from app.speaker.embedding import normalized
    store=MemoryStore()
    vectors=[[1,0,0],[1,.2,0],[1,0,.2]]
    iterator=iter(vectors)
    engine.extract=lambda *a,**kw: next(iterator)
    result=service(configuration,engine,quality,policy,store).enroll(
        [(uuid4(),audio()) for _ in range(3)],EnrollmentConsent(enrollment=True,persistence=True))
    expected=normalized(np.mean([normalized(v,3) for v in vectors],axis=0),3)
    assert np.allclose(store.load(result.profile_id).template,expected)

def test_bad_quality_no_extraction(configuration,engine,quality,policy):
    store=MemoryStore()
    def fail(*a,**kw): raise AssertionError("should_not_extract")
    engine.extract=fail
    result=service(configuration,engine,quality,policy,store).enroll(
        [(uuid4(),object()) for _ in range(3)],EnrollmentConsent(enrollment=True,persistence=True))
    assert result.reason=="invalid_audio" and not store.values
