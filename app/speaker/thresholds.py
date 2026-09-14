"""Cosine boundaries; synthetic policies cannot authorize the production gateway."""
import math
from app.speaker.contracts import SpeakerError
from app.speaker.models import ThresholdConfiguration

class BoundedThresholdPolicy:
    def __init__(self, configuration: ThresholdConfiguration):
        self.configuration = ThresholdConfiguration.model_validate(configuration.model_dump())
    def decide(self, score):
        if isinstance(score, bool) or not math.isfinite(score) or not -1 <= score <= 1:
            raise SpeakerError("invalid_embedding")
        cfg = self.configuration
        if cfg.calibration == "pending":
            raise SpeakerError("unavailable")
        if score >= cfg.acceptance:
            return "verified"
        if cfg.review is not None and score >= cfg.review:
            return "uncertain"
        return "rejected"
