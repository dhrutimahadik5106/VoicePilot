from threading import Event
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.speaker.models import VerificationResult
from app.speaker.pipeline import SpeakerGateway

def result(profile,policy,quality,audio,audio_id,status="verified",calibration="validated"):
    cfg=policy.configuration.model_copy(update={"calibration":calibration})
    return VerificationResult(attempt_id=uuid4(),audio_id=audio_id,profile_id=profile.profile_id,
        model=profile.model,policy=cfg,quality=quality.assess(audio),status=status,
        reason="ok",similarity=1.)

def setup(profile,policy,quality,audio,status="verified",calibration="validated"):
    calls=[]
    def verify(a,p,*,audio_id,cancel):
        calls.append(("verify",a))
        return result(profile,policy,quality,a,audio_id,status,calibration)
    def stt(a,*,audio_id,cancel):
        calls.append(("stt",a))
        return SimpleNamespace(status="succeeded",audio_id=audio_id)
    def resolve(r):
        calls.append(("resolve",r))
        return SimpleNamespace(execution_permitted=False)
    return SpeakerGateway(SimpleNamespace(verify=verify),SimpleNamespace(transcribe_audio=stt),
                          SimpleNamespace(resolve_stt=resolve)),calls

@pytest.mark.parametrize("status",["rejected","uncertain","unavailable","cancelled","invalid_audio","invalid_profile"])
def test_all_block(profile,policy,quality,audio,status):
    gateway,calls=setup(profile,policy,quality,audio,status)
    r=gateway.run(audio(),profile.profile_id)
    assert r.status=="blocked" and [c[0] for c in calls]==["verify"]

def test_same_buffer(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio)
    a=audio()
    r=gateway.run(a,profile.profile_id)
    assert r.status=="completed" and calls[0][1] is calls[1][1] is a
    assert not r.execution_permitted
    assert "transcription" not in r.model_dump()
    assert "resolution" not in r.model_dump()

def test_synthetic_blocked(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio,calibration="synthetic")
    assert gateway.run(audio(),profile.profile_id).reason=="calibration_pending"
    assert len(calls)==1

def test_stale_binding(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio)
    old=result(profile,policy,quality,audio(),uuid4())
    gateway.verification.verify=lambda *a,**kw: old
    assert gateway.run(audio(),profile.profile_id).reason=="binding_mismatch"
    assert calls==[]

def test_cancel_after_verification(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio)
    event=Event()
    original=gateway.verification.verify
    def verify(*a,**kw):
        r=original(*a,**kw)
        event.set()
        return r
    gateway.verification.verify=verify
    assert gateway.run(audio(),profile.profile_id,cancel=event).status=="cancelled"
    assert len(calls)==1

def test_no_boolean_parameter(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio)
    with pytest.raises(TypeError): gateway.run(audio(),profile.profile_id,speaker_verified=True)
    assert not calls

def test_stt_failure_no_resolution(profile,policy,quality,audio):
    gateway,calls=setup(profile,policy,quality,audio)
    gateway.stt.transcribe_audio=lambda *a,**kw: SimpleNamespace(status="unusable_audio",audio_id=kw["audio_id"])
    assert gateway.run(audio(),profile.profile_id).reason=="stt_rejected"
    assert [c[0] for c in calls]==["verify"]

def test_backend_error(profile,policy,quality,audio,capsys):
    gateway,calls=setup(profile,policy,quality,audio)
    def fail(*a,**kw): raise RuntimeError("PRIVATE_AUDIO")
    gateway.verification.verify=fail
    r=gateway.run(audio(),profile.profile_id)
    assert r.status=="blocked" and not calls
    assert "PRIVATE_AUDIO" not in repr(r)+capsys.readouterr().out

@pytest.mark.parametrize("stage",["stt","resolver"])
def test_cancellation_discards_downstream(profile,policy,quality,audio,stage):
    gateway,calls=setup(profile,policy,quality,audio)
    event=Event()
    if stage=="stt":
        original=gateway.stt.transcribe_audio
        def wrapped(*a,**kw):
            value=original(*a,**kw)
            event.set()
            return value
        gateway.stt.transcribe_audio=wrapped
    else:
        original=gateway.resolver.resolve_stt
        def wrapped(*a,**kw):
            value=original(*a,**kw)
            event.set()
            return value
        gateway.resolver.resolve_stt=wrapped
    value=gateway.run(audio(),profile.profile_id,cancel=event)
    assert value.status=="cancelled"
    assert value.transcription is None and value.resolution is None
    if stage=="stt": assert len(calls)==2

def test_existing_stt_safety_runs_before_resolver(profile,policy,quality,audio):
    from app.core.config import Settings
    from app.stt.service import TranscriptionService
    from app.stt.models import TranscriptionResult, TranscriptSegment
    class Engine:
        def transcribe(self, request, *, cancel=None):
            return TranscriptionResult(audio_id=request.audio_id,model_name="synthetic",
                device="cpu",compute_type="int8",status="succeeded",language="en",
                source_audio_duration=1,processing_duration=0,
                text=("echo "*100).strip(),segments=(TranscriptSegment(text="echo "*100,start=0,end=1),))
    gateway,calls=setup(profile,policy,quality,audio)
    gateway.stt=TranscriptionService(Settings(),Engine())
    result=gateway.run(audio(),profile.profile_id)
    assert result.status=="blocked" and result.reason=="stt_rejected"
    assert len(calls)==1
