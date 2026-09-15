from types import SimpleNamespace
from uuid import uuid4
from threading import Event
import pytest
from app.core.config import Settings
from app.pipeline.service import DiagnosticService,SpeakerInspection
from app.speaker.models import VerificationResult,ModelIdentity,ThresholdConfiguration,SpeakerQualitySummary
from tests.pipeline.helpers import audio,STT,transcription

@pytest.mark.parametrize("status",["rejected","uncertain","unavailable","invalid_audio","invalid_profile","cancelled"])
def test_auth_denial_never_stt(status):
    stt=STT()
    def verify(a,p,*,audio_id,cancel=None):
        return VerificationResult(attempt_id=uuid4(),audio_id=audio_id,profile_id=p,status=status,
            reason="cancelled" if status=="cancelled" else "calibration_pending")
    service=DiagnosticService(Settings(),stt=stt,verifier=SimpleNamespace(verify=verify))
    trace=service.audio(audio(),authenticated=True,profile_id=uuid4())
    assert trace.authentication=="denied" and trace.stt_status=="not_called" and not stt.calls
    assert not trace.execution_permitted

def verified(a,p,*,audio_id,cancel=None):
    m=ModelIdentity(name="fake",revision="v1",sha256="0"*64,dimension=3,preprocessing="fake")
    policy=ThresholdConfiguration(version="fake-v1",model=m,acceptance=.8,calibration="validated")
    return VerificationResult(attempt_id=uuid4(),audio_id=audio_id,profile_id=p,status="verified",reason="ok",
        model=m,similarity=.91,policy=policy,quality=SpeakerQualitySummary(eligible=True,reason="ok"))

def test_verified_same_buffer_and_no_biometric_trace():
    stt=STT();a=audio();seen=[]
    def verify(*args,**kwargs):seen.append(args[0]);return verified(*args,**kwargs)
    s=DiagnosticService(Settings(speaker_verification_enabled=True),stt=stt,verifier=SimpleNamespace(verify=verify))
    result=s.audio(a,authenticated=True,profile_id=uuid4())
    assert result.status=="completed" and result.authentication=="policy_verified"
    assert seen[0] is a and stt.calls[0][0] is a
    assert stt.calls[0][1]==result.trace_id
    out=str(result.public(include_text=True))
    for forbidden in ('similarity','embedding','sha256','profile_id','template','segments'):
        assert repr(forbidden)+':' not in out
    assert not result.execution_permitted

@pytest.mark.parametrize("mismatch",["audio","profile","disabled","reuse"])
def test_auth_binding(mismatch):
    old=[None];stt=STT()
    def verify(a,p,*,audio_id,cancel=None):
        if mismatch=="audio":audio_id=uuid4()
        if mismatch=="profile":p=uuid4()
        if mismatch=="reuse" and old[0] is not None:return old[0]
        old[0]=verified(a,p,audio_id=audio_id);return old[0]
    s=DiagnosticService(Settings(speaker_verification_enabled=mismatch!="disabled"),stt=stt,verifier=SimpleNamespace(verify=verify))
    first=s.audio(audio(),authenticated=True,profile_id=uuid4())
    if mismatch=="reuse":
        stt.calls.clear();first=s.audio(audio(),authenticated=True,profile_id=uuid4())
    assert first.status=="blocked" and not stt.calls

def test_voice_raw_normalized_canonical():
    stt=STT("  open Spotify  ");a=audio();s=DiagnosticService(Settings(),stt=stt)
    r=s.audio(a)
    assert stt.calls[0][0] is a and r.authentication=="unauthenticated_diagnostic"
    assert r.details.raw_transcript=="  open Spotify  "
    assert r.details.stt_normalized_transcript=="open Spotify"
    assert r.details.resolver_normalized_transcript=="open spotify"
    assert r.details.canonical_command=="Open Spotify"
    assert 'raw_transcript' not in r.model_dump_json()+repr(r)

@pytest.mark.parametrize("status",["failed","unusable_audio","cancelled"])
def test_stt_failure(status):
    s=DiagnosticService(Settings(),stt=STT(status=status));r=s.audio(audio())
    assert r.status in {"blocked","cancelled"} and r.plan is None and r.details is None

def test_cancel_discards():
    event=Event();stt=STT();s=DiagnosticService(Settings(),stt=stt)
    event.set();r=s.audio(audio(),cancel=event)
    assert r.status=="cancelled" and not stt.calls and r.details is None
    assert s.text("open Spotify",cancel=event).details is None

def test_sensitive_text_never_displayed():
    s=DiagnosticService(Settings());r=s.text("password SECRET_MARKER")
    assert r.status=="blocked" and r.details is None
    assert "SECRET_MARKER" not in str(r.public(include_text=True))+repr(r)

def test_pending_uses_policy_boundary_before_engine(monkeypatch):
    from app.speaker import interactive
    from app.speaker.contracts import SpeakerError
    called=[]
    class Session:
        def __init__(self,settings):pass
        def repository(self):return SimpleNamespace(load=lambda p:object())
        def policy(self,profile,key):called.append("policy");raise SpeakerError("calibration_pending")
        def ready(self):pytest.fail("pending_policy_must_not_load_model")
    monkeypatch.setattr(interactive,"LocalSpeakerSession",Session)
    stt=STT();settings=Settings()
    s=DiagnosticService(settings,stt=stt,verifier=SpeakerInspection(settings))
    r=s.audio(audio(),authenticated=True,profile_id=uuid4())
    assert called==["policy"] and r.reason=="access_denied" and not stt.calls

def test_adapter_delegates_existing_verifier(monkeypatch):
    from app.speaker import interactive,verification
    seen=[];a=audio();profile=uuid4();aid=uuid4()
    class Session:
        def __init__(self,settings):self.engine=object()
        def repository(self):return SimpleNamespace(load=lambda p:object())
        def policy(self,p,key):return object()
        def ready(self):seen.append("ready")
    class ExistingVerifier:
        def __init__(self,*args):pass
        def verify(self,buffer,p,**kwargs):seen.append((buffer,p,kwargs["audio_id"]));return verified(buffer,p,**kwargs)
    monkeypatch.setattr(interactive,"LocalSpeakerSession",Session)
    monkeypatch.setattr(verification,"VerificationService",ExistingVerifier)
    r=SpeakerInspection(Settings(),uuid4()).verify(a,profile,audio_id=aid)
    assert r.status=="verified" and seen[1][0] is a and seen[1][1:]==(profile,aid)


def test_existing_stt_safety_precedes_planning():
    from app.stt.service import TranscriptionService
    class Engine:
        def transcribe(self,request,cancel=None):
            return transcription(request.audio_id,"hello "*80)
    stt=TranscriptionService(Settings(),Engine())
    service=DiagnosticService(Settings(),stt=stt)
    result=service.audio(audio())
    assert result.status=="blocked" and result.reason=="unsuccessful_stt"
    assert result.stt_status=="unusable_audio" and result.details is None and result.plan is None

def test_boolean_is_not_authentication():
    stt=STT();service=DiagnosticService(Settings(speaker_verification_enabled=True),stt=stt,
        verifier=SimpleNamespace(verify=lambda *args,**kwargs:True))
    result=service.audio(audio(),authenticated=True,profile_id=uuid4())
    assert result.status=="blocked" and not stt.calls


def test_private_language_metadata_is_not_exposed():
    def transcribe(a,*,audio_id,cancel=None):
        return transcription(audio_id).model_copy(update={"language":"SECRET_MARKER"})
    service=DiagnosticService(Settings(),stt=SimpleNamespace(transcribe_audio=transcribe))
    result=service.audio(audio())
    assert result.status=="blocked" and result.reason=="invalid_input"
    assert "SECRET_MARKER" not in str(result.public(include_text=True))
