"""Explicit consent and all-sample enrollment, using injected dependencies."""
from datetime import datetime, timezone
from uuid import uuid4
import numpy as np
from app.speaker.contracts import SpeakerError
from app.speaker.embedding import normalized, cosine
from app.speaker.models import EnrollmentResult, EnrollmentSampleResult, SpeakerProfile
from app.speaker.profiles import check_cancel

class EnrollmentService:
    def __init__(self, configuration, engine, quality, repository, policy,
                 *, clock=lambda: datetime.now(timezone.utc), ids=uuid4):
        self.configuration, self.engine, self.quality = configuration, engine, quality
        self.repository, self.policy, self.clock, self.ids = repository, policy, clock, ids

    def enroll(self, samples, consent, *, cancel=None, profile_id=None):
        vectors, outcomes = [], []
        def failure(reason, status="rejected"):
            return EnrollmentResult(status=status, reason=reason)
        try:
            check_cancel(cancel)
            if not consent.enrollment:
                return failure("consent_required")
            if not consent.persistence:
                return failure("persistence_consent_required")
            cfg = self.configuration
            if not isinstance(samples, (list, tuple)) or not cfg.min_samples <= len(samples) <= cfg.max_samples:
                return failure("sample_count")
            # Separate capture identifiers and distinct buffers are required. This is
            # provenance supplied by the capture adapter, not proof against replay.
            if len({sid for sid, _ in samples}) != len(samples) or len({id(a) for _, a in samples}) != len(samples):
                return failure("duplicate_sample")
            model = self.engine.identity
            if model is None:
                return failure("unavailable", "unavailable")
            if model.dimension != cfg.embedding_dimension or self.policy.configuration.model != model:
                return failure("incompatible_profile")
            for sample_id, audio in samples:
                check_cancel(cancel)
                quality = self.quality.assess(audio)
                if not quality.eligible:
                    return failure("invalid_audio")
                check_cancel(cancel)
                vector = normalized(self.engine.extract(audio, cancel=cancel), model.dimension)
                check_cancel(cancel)
                vectors.append(vector)
                outcomes.append(EnrollmentSampleResult(sample_id=sample_id, accepted=True, quality=quality, reason="ok"))
            if any(cosine(a, b, model.dimension) < cfg.consistency_threshold
                   for i, a in enumerate(vectors) for b in vectors[i+1:]):
                return failure("inconsistent_samples")
            aggregate = normalized(np.mean(vectors, axis=0), model.dimension)
            check_cancel(cancel)
            now = self.clock()
            created = now
            if profile_id is not None:
                created = self.repository.load(profile_id).created_at
            profile = SpeakerProfile(profile_id=profile_id or self.ids(), model=model,
                template=aggregate, sample_count=len(vectors), created_at=created, updated_at=now,
                policy_version=self.policy.configuration.version,
                calibration=self.policy.configuration.calibration)
            check_cancel(cancel)
            self.repository.save(profile, cancel=cancel)
            return EnrollmentResult(status="enrolled", profile_id=profile.profile_id,
                                    reason="ok", samples=tuple(outcomes))
        except SpeakerError as error:
            return failure(error.code, "cancelled" if error.code == "cancelled" else
                           "unavailable" if error.code == "unavailable" else "rejected")
        except Exception:
            return failure("backend_failed", "unavailable")
        finally:
            vectors.clear()
            outcomes.clear()
            # Caller owns capture buffers. No service field retains them; Python
            # reference release is not a secure-memory-erasure guarantee.
