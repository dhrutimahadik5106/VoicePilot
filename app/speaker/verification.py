"""Nominated-profile verification. No audio retention or downstream actions."""
from time import perf_counter
from uuid import uuid4
from app.speaker.contracts import SpeakerError
from app.speaker.embedding import cosine, normalized
from app.speaker.models import VerificationResult, SpeakerProfile
from app.speaker.profiles import check_cancel

class VerificationService:
    def __init__(self, engine, quality, repository, policy, *, clock=perf_counter, ids=uuid4):
        self.engine, self.quality, self.repository, self.policy = engine, quality, repository, policy
        self.clock, self.ids = clock, ids

    def verify(self, audio, profile_id, *, audio_id, cancel=None):
        started, attempt = self.clock(), self.ids()
        def result(status, reason, **values):
            return VerificationResult(attempt_id=attempt, audio_id=audio_id, profile_id=profile_id,
                status=status, reason=reason, processing_duration=max(0, self.clock()-started), **values)
        try:
            check_cancel(cancel)
            model = self.engine.identity
            if model is None or self.policy is None:
                return result("unavailable", "unavailable")
            cfg = self.policy.configuration
            profile = self.repository.load(profile_id)
            profile = SpeakerProfile.model_validate(profile.model_dump() | {"template": profile.template, "enrollment_hashes": profile.enrollment_hashes})
            if (profile.profile_id != profile_id or profile.model != model or cfg.model != model
                    or profile.policy_version != cfg.version or profile.calibration != cfg.calibration):
                return result("invalid_profile", "incompatible_profile")
            if cfg.calibration == "pending":
                return result("unavailable", "calibration_pending")
            check_cancel(cancel)
            quality = self.quality.assess(audio)
            if not quality.eligible:
                return result("invalid_audio", "invalid_audio", quality=quality)
            check_cancel(cancel)
            vector = normalized(self.engine.extract(audio, cancel=cancel), model.dimension)
            check_cancel(cancel)
            score = cosine(vector, profile.template, model.dimension)
            status = self.policy.decide(score)
            check_cancel(cancel)
            return result(status, {"verified":"ok", "rejected":"below_threshold", "uncertain":"review_required"}[status],
                          model=model, similarity=score, policy=cfg, quality=quality)
        except SpeakerError as error:
            status = {"cancelled":"cancelled", "invalid_profile":"invalid_profile",
                      "incompatible_profile":"invalid_profile", "invalid_audio":"invalid_audio",
                      "invalid_embedding":"invalid_audio"}.get(error.code, "unavailable")
            return result(status, error.code)
        except Exception:
            return result("unavailable", "backend_failed")
