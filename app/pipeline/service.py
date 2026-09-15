"""One-buffer diagnostics; authenticated checks precede all STT access."""
from time import perf_counter
from uuid import uuid4
from app.commands.resolver import CommandResolver
from app.planning.planner import Planner
from app.planning.simulator import Simulator
from app.pipeline.models import Trace,Details
from app.planning.risk import SENSITIVE
from app.speaker.models import VerificationResult
from app.stt.models import TranscriptionResult

class DiagnosticService:
    def __init__(self, settings, *, stt=None, verifier=None, resolver=None, clock=perf_counter):
        self.settings,self.stt,self.verifier,self.clock=settings,stt,verifier,clock
        self.resolver=resolver or CommandResolver.from_directory()
        self.planner=Planner(settings.planning,resolver=self.resolver)
        self.simulator=Simulator(settings.planning)

    def _finish(self,raw,normalized,base,cancel):
        if cancel is not None and cancel.is_set(): return Trace(**base,status="cancelled",reason="cancelled")
        if not isinstance(raw,str) or len(raw)>500: return Trace(**base,status="blocked",reason="invalid_input")
        if SENSITIVE.search(raw): return Trace(**base,status="blocked",reason="sensitive_input")
        start=self.clock()
        resolution=self.resolver.resolve(raw,language=base.get("language") if base.get("language") in {"en","hi","mr"} else "mixed")
        plan=self.planner.build(resolution,trace_id=base["trace_id"],authentication=base.get("authentication","unauthenticated_diagnostic"))
        simulation=self.simulator.run(plan,cancel=cancel)
        if cancel is not None and cancel.is_set(): return Trace(**base,status="cancelled",reason="cancelled")
        details=Details(raw_transcript=raw,stt_normalized_transcript=normalized,
            resolver_normalized_transcript=resolution.normalized_transcript,entities=resolution.entities,
            canonical_command=resolution.canonical_command,proposed_objective=plan.objective)
        return Trace(**base,status="completed",reason="ok",resolver_status=resolution.status,intent=resolution.intent,
            plan=plan,simulation=simulation,details=details,resolver_reasons=resolution.reasons,
            resolver_evidence=tuple(sorted({c.match_type for c in resolution.candidates})),planning_seconds=max(0,self.clock()-start))

    def text(self,text,*,session_id=None,cancel=None):
        start=self.clock();base=dict(mode="unauthenticated-text",trace_id=uuid4(),session_id=session_id or uuid4())
        try: result=self._finish(text,text,base,cancel)
        except Exception: result=Trace(**base,status="blocked",reason="pipeline_failed")
        return result.model_copy(update={"total_seconds":max(0,self.clock()-start)})

    def audio(self,audio,*,authenticated=False,profile_id=None,session_id=None,cancel=None,capture_seconds=0):
        start=self.clock();base=dict(mode="authenticated" if authenticated else "unauthenticated-voice",
            trace_id=uuid4(),session_id=session_id or uuid4(),authentication="denied" if authenticated else "unauthenticated_diagnostic")
        def stopped(status,reason):
            return Trace(**base,status=status,reason=reason,total_seconds=max(0,self.clock()-start)+capture_seconds)
        try:
            if cancel is not None and cancel.is_set(): return stopped("cancelled","cancelled")
            base.update(duration=audio.duration,sample_rate=audio.format.sample_rate,channels=audio.format.channels,capture_seconds=capture_seconds)
            if authenticated:
                if self.verifier is None or profile_id is None: return stopped("blocked","access_denied")
                v=self.verifier.verify(audio,profile_id,audio_id=base["trace_id"],cancel=cancel)
                v=VerificationResult.model_validate(v.model_dump())
                if cancel is not None and cancel.is_set(): return stopped("cancelled","cancelled")
                if (not self.settings.speaker_verification_enabled or v.status!="verified" or v.audio_id!=base["trace_id"]
                    or v.profile_id!=profile_id or v.policy is None or v.policy.calibration!="validated"):
                    return stopped("blocked","access_denied")
                base["authentication"]="policy_verified"
            if self.stt is None:
                from app.stt.service import TranscriptionService
                from app.stt.faster_whisper_engine import FasterWhisperEngine
                local=self.settings.model_copy(update={"stt_local_files_only":True})
                self.stt=TranscriptionService(local,FasterWhisperEngine(local))
            stt_start=self.clock()
            result=self.stt.transcribe_audio(audio,audio_id=base["trace_id"],cancel=cancel)
            result=TranscriptionResult.model_validate(result.model_dump(exclude_computed_fields=True))
            base["stt_seconds"]=max(0,self.clock()-stt_start)
            if cancel is not None and cancel.is_set() or result.status=="cancelled": return stopped("cancelled","cancelled")
            base["stt_status"]=result.status
            if result.status!="succeeded" or result.audio_id!=base["trace_id"]:
                return stopped("blocked","unsuccessful_stt")
            import re
            if not isinstance(result.language,str) or not re.fullmatch(r"[a-z]{2,3}",result.language):
                return stopped("blocked","invalid_input")
            base["language"]=result.language
            trace=self._finish(result.raw_transcript,result.normalized_transcript,base,cancel)
            return trace.model_copy(update={"total_seconds":max(0,self.clock()-start)+capture_seconds})
        except Exception:
            return stopped("blocked","pipeline_failed")

class SpeakerInspection:
    """Delegate to Phase 4B policy validation and verifier; never invent thresholds."""
    def __init__(self,settings,policy_id=None):
        self.settings,self.policy_id=settings,policy_id
    def verify(self,audio,profile_id,*,audio_id,cancel=None):
        from app.speaker.interactive import LocalSpeakerSession
        from app.speaker.profiles import check_cancel
        from app.speaker.verification import VerificationService
        from app.speaker.quality import NumericalQuality
        from app.speaker.contracts import SpeakerError
        try:
            check_cancel(cancel)
            session=LocalSpeakerSession(self.settings)
            repository=session.repository()
            profile=repository.load(profile_id)
            # This is the existing protected approval/provenance boundary. Missing
            # or pending policy fails BEFORE model loading, extraction or STT.
            policy=session.policy(profile,self.policy_id)
            check_cancel(cancel)
            session.ready()
            verifier=VerificationService(session.engine,NumericalQuality(self.settings.speaker),repository,policy)
            return verifier.verify(audio,profile_id,audio_id=audio_id,cancel=cancel)
        except SpeakerError as error:
            reason=error.code
        except Exception:
            reason="unavailable"
        return VerificationResult(attempt_id=uuid4(),audio_id=audio_id,profile_id=profile_id,
            status="cancelled" if reason=="cancelled" else "unavailable",reason=reason)
