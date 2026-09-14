"""Fresh verification on the same buffer; no execution dependency exists."""
from uuid import uuid4
from app.speaker.models import PipelineResult, VerificationResult

class SpeakerGateway:
    def __init__(self, verification, stt, resolver, *, ids=uuid4):
        self.verification, self.stt, self.resolver, self.ids = verification, stt, resolver, ids

    def run(self, audio, profile_id, *, cancel=None):
        cancelled = lambda: cancel is not None and cancel.is_set()
        if cancelled():
            return PipelineResult(status="cancelled", reason="cancelled")
        try:
            audio_id = self.ids()
            verification = self.verification.verify(audio, profile_id, audio_id=audio_id, cancel=cancel)
            # Revalidate even injected model instances before making a gate decision.
            verification = VerificationResult.model_validate(verification.model_dump())
            if cancelled():
                return PipelineResult(status="cancelled", reason="cancelled")
            if verification.audio_id != audio_id or verification.profile_id != profile_id:
                return PipelineResult(status="blocked", reason="binding_mismatch")
            if verification.status != "verified":
                return PipelineResult(status="blocked", reason=verification.reason, verification=verification)
            # Synthetic and pending policies NEVER authorize this gateway.
            if verification.policy.calibration != "validated":
                return PipelineResult(status="blocked", reason="calibration_pending", verification=verification)
            if cancelled():
                return PipelineResult(status="cancelled", reason="cancelled")
            transcription = self.stt.transcribe_audio(audio, audio_id=audio_id, cancel=cancel)
            if cancelled():
                return PipelineResult(status="cancelled", reason="cancelled")
            if transcription.status != "succeeded" or transcription.audio_id != audio_id:
                return PipelineResult(status="blocked", reason="stt_rejected", verification=verification)
            # STT dependency is the existing safety-applying TranscriptionService.
            resolution = self.resolver.resolve_stt(transcription)
            if cancelled():
                return PipelineResult(status="cancelled", reason="cancelled")
            if resolution.execution_permitted:
                return PipelineResult(status="blocked", reason="downstream_failed")
            return PipelineResult(status="completed", reason="ok", verification=verification,
                                  transcription=transcription, resolution=resolution)
        except Exception:
            return PipelineResult(status="blocked", reason="backend_failed")
