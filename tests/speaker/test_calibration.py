from datetime import datetime, timezone
from uuid import UUID,uuid4
import pytest
from app.speaker.calibration import (ConsentedTrial,validate_private_trials,freeze,
    evaluate_private,approve_frozen,record_trial,waveform_hash)
from app.speaker.private_store import PrivateRecords
from app.speaker.contracts import SpeakerError
from tests.speaker.conftest import FakeProtector,MemoryStore

def row(identity,index=1,**changes):
    values=dict(record_id=UUID(int=1000+index),target=UUID(int=1),speaker=UUID(int=1),
        session=UUID(int=20+index%2),enrollment_session=UUID(int=10),recording_group=UUID(int=100+index),
        audio_sha256=format(index,"064x"),enrollment_hashes=("f"*64,),split="validation",
        consent=True,impostor_consent=False,model=identity,score=.9,language="en",condition="quiet",
        created_at=datetime.now(timezone.utc).isoformat())
    return ConsentedTrial(**(values|changes))

def test_explicit_consent(profile,engine,audio,tmp_path):
    with pytest.raises(SpeakerError,match="consent_required"):
        record_trial(audio(),profile,engine,PrivateRecords(tmp_path,FakeProtector()),
            speaker=profile.profile_id,session=uuid4(),group=uuid4(),split="validation",
            consent=False,impostor_consent=False,language="en",condition="quiet")

@pytest.mark.parametrize("changes",[
    {"session":UUID(int=10)},{"audio_sha256":"f"*64},
    {"speaker":UUID(int=2),"impostor_consent":False}])
def test_bad_trial(identity,changes):
    with pytest.raises(SpeakerError):validate_private_trials([row(identity,**changes)])

def test_cross_split(identity):
    with pytest.raises(SpeakerError):validate_private_trials([row(identity),row(identity,2,split="test")])

def test_group_leakage(identity):
    a=row(identity)
    b=row(identity,2,target=UUID(int=5),speaker=UUID(int=5),session=UUID(int=99),
          enrollment_session=UUID(int=98),split="test",recording_group=a.recording_group)
    with pytest.raises(SpeakerError):validate_private_trials([a,b])

def test_freeze_no_evidence(tmp_path,identity):
    with pytest.raises(SpeakerError,match="calibration_pending"):
        freeze(PrivateRecords(tmp_path,FakeProtector()),identity,.8,.5,consent=True)

def test_freeze_eval_and_no_small_approval(tmp_path,identity,profile):
    store=PrivateRecords(tmp_path,FakeProtector())
    r=row(identity);store.save(r.record_id,r.private_document())
    key=freeze(store,identity,.8,.5,consent=True)
    report=evaluate_private(store,key,"validation",consent=True)
    assert report["genuine_acceptance"]["numerator"]==1
    assert report["far"]["value"] is None
    assert report["scope"]=="personal_development_only"
    assert not report["authorization_approved"]
    with pytest.raises(SpeakerError,match="calibration_pending"):
        approve_frozen(store,MemoryStore(profile),key,profile.profile_id,reviewed=True)

def enough(store,identity,provenance=None):
    for i in range(1,41):
        r=row(identity,i,speaker=UUID(int=1 if i<=20 else 2+i%3),
              impostor_consent=i>20,score=.95 if i<=20 else .2,provenance=provenance)
        store.save(r.record_id,r.private_document())

def test_explicit_approval(tmp_path,identity,profile):
    from app.speaker.provenance import binding
    profile=profile.model_copy(update={"enrollment_session":UUID(int=10),"enrollment_hashes":("f"*64,)})
    store=PrivateRecords(tmp_path,FakeProtector());enough(store,identity,binding(profile))
    frozen=freeze(store,identity,.8,.5,consent=True)
    repo=MemoryStore(profile)
    with pytest.raises(SpeakerError,match="consent_required"):
        approve_frozen(store,repo,frozen,profile.profile_id)
    approved=approve_frozen(store,repo,frozen,profile.profile_id,reviewed=True)
    assert store.load(approved)["authorization_approved"]
    assert repo.load(profile.profile_id).calibration=="validated"
    assert store.load(approved)["provenance"]==binding(repo.load(profile.profile_id))
    from app.core.config import Settings
    from app.speaker.interactive import LocalSpeakerSession
    from types import SimpleNamespace
    session=LocalSpeakerSession(Settings(),engine=SimpleNamespace(identity=identity))
    session.records=lambda **kwargs:store
    current=repo.load(profile.profile_id)
    assert session.policy(current,approved).configuration.calibration=="validated"
    with pytest.raises(SpeakerError):
        session.policy(current.model_copy(update={"enrollment_session":uuid4()}),approved)


def test_freeze_after_test_refused(tmp_path,identity):
    store=PrivateRecords(tmp_path,FakeProtector())
    a=row(identity);store.save(a.record_id,a.private_document())
    b=row(identity,2,split="test",speaker=UUID(int=99),target=UUID(int=99),
          session=UUID(int=98),enrollment_session=UUID(int=97))
    store.save(b.record_id,b.private_document())
    with pytest.raises(SpeakerError):freeze(store,identity,.8,.5,consent=True)

def test_record_enrollment_reuse(profile,engine,audio,tmp_path):
    a=audio()
    p=profile.model_copy(update={"enrollment_session":uuid4(),"enrollment_hashes":(waveform_hash(a),)})
    with pytest.raises(SpeakerError,match="invalid_audio"):
        record_trial(a,p,engine,PrivateRecords(tmp_path,FakeProtector()),speaker=p.profile_id,
            session=uuid4(),group=uuid4(),split="validation",consent=True,impostor_consent=False,
            language="en",condition="quiet")

@pytest.mark.parametrize("change", ["session", "hash", "template", "model", "profile", "missing", "mixed", "timestamp", "missing_enrollment"])
def test_stale_binding_rejected(tmp_path, identity, profile, change):
    import numpy as np
    from app.speaker.provenance import binding
    profile=profile.model_copy(update={"enrollment_session":UUID(int=10),"enrollment_hashes":("f"*64,)})
    store=PrivateRecords(tmp_path,FakeProtector())
    enough(store,identity,None if change=="missing" else binding(profile))
    if change=="mixed":
        r=row(identity,41,provenance="a"*64)
        store.save(r.record_id,r.private_document())
    frozen=freeze(store,identity,.8,.5,consent=True)
    changes={"session":{"enrollment_session":uuid4()}, "hash":{"enrollment_hashes":("a"*64,)},
        "template":{"template":np.array([0.,1.,0.])},
        "model":{"model":identity.model_copy(update={"revision":"other"})},
        "profile":{"profile_id":uuid4()}, "missing_enrollment":{"enrollment_session":None}, "timestamp":{"updated_at":datetime.now(timezone.utc)}}
    current=profile.model_copy(update=changes.get(change,{}))
    with pytest.raises(SpeakerError) as error:
        approve_frozen(store,MemoryStore(current),frozen,current.profile_id,reviewed=True)
    assert binding(profile) not in str(error.value)
    assert "provenance" not in repr(row(identity,provenance=binding(profile)))
    assert "provenance" not in row(identity,provenance=binding(profile)).model_dump()

@pytest.mark.parametrize("outcome", ["success", "failed", "cancelled"])
def test_reenrollment_authorization_lifecycle(configuration, engine, quality, policy, audio, profile, outcome):
    from threading import Event
    from app.speaker.enrollment import EnrollmentService
    from app.speaker.models import EnrollmentConsent
    from app.speaker.provenance import binding
    profile=profile.model_copy(update={"enrollment_session":uuid4(), "enrollment_hashes":("f"*64,),
        "calibration":"validated", "policy_version":"approved-existing"})
    old=binding(profile)
    repo=MemoryStore(profile)
    event=Event()
    if outcome=="cancelled": event.set()
    if outcome=="failed": engine.extract=lambda *a,**kw: [0,0,0]
    result=EnrollmentService(configuration,engine,quality,repo,policy).enroll(
        [(uuid4(),audio()) for _ in range(4)], EnrollmentConsent(enrollment=True,persistence=True),
        profile_id=profile.profile_id,enrollment_session=uuid4(),cancel=event)
    current=repo.load(profile.profile_id)
    if outcome=="success":
        assert result.status=="enrolled"
        assert current.calibration=="pending" and current.policy_version=="calibration-pending"
        assert binding(current)!=old
    else:
        assert result.status!="enrolled"
        assert current is profile and binding(current)==old
        assert current.calibration=="validated" and current.policy_version=="approved-existing"

def test_binding_survives_private_roundtrip(tmp_path,profile):
    from app.speaker.models import SpeakerProfile
    from app.speaker.profiles import ProtectedProfileRepository
    from app.speaker.provenance import binding
    import numpy as np
    vector=np.array([.3,.4,.8]);vector/=np.linalg.norm(vector)
    p=SpeakerProfile(**(profile.model_dump()|{"template":vector,"enrollment_session":uuid4(),"enrollment_hashes":("f"*64,)}))
    repo=ProtectedProfileRepository(tmp_path,FakeProtector())
    repo.save(p)
    assert binding(repo.load(p.profile_id))==binding(p)

def test_private_failed_acquisition_coverage(tmp_path,identity):
    store=PrivateRecords(tmp_path,FakeProtector())
    for r in (row(identity),row(identity,2,score=None,outcome="invalid_audio")):
        store.save(r.record_id,r.private_document())
    key=freeze(store,identity,.8,.5,consent=True)
    report=evaluate_private(store,key,"validation",consent=True)
    assert report["coverage"]["numerator"]==1
    assert report["coverage"]["denominator"]==2
    assert report["failure_to_acquire"]==1

def test_private_validation_report_uses_frozen_rows(tmp_path,identity):
    store=PrivateRecords(tmp_path,FakeProtector())
    r=row(identity);store.save(r.record_id,r.private_document())
    key=freeze(store,identity,.8,.5,consent=True)
    r=row(identity,2);store.save(r.record_id,r.private_document())
    assert evaluate_private(store,key,"validation",consent=True)["total"]==1

def test_private_invalid_payload_error_is_safe(identity):
    r=row(identity)
    with pytest.raises(SpeakerError) as error:
        ConsentedTrial(**(r.private_document()|{"provenance":"PRIVATE_MARKER"}))
    assert "PRIVATE_MARKER" not in str(error.value)+repr(error.value)
    assert not hasattr(error.value,"errors")
