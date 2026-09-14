"""No detector is provided in Phase 4A."""
from app.speaker.models import AntiSpoofingResult
class UnavailableAntiSpoofing:
    def assess(self, audio):
        return AntiSpoofingResult(status="unavailable")
