"""Replaceable boundaries; errors contain only allowlisted codes."""
from threading import Event
from typing import Protocol
from uuid import UUID
from app.audio.models import RecordedAudio
from app.speaker.models import (ModelIdentity, SpeakerProfile, SpeakerQualitySummary,
    ThresholdConfiguration, VerificationResult, AntiSpoofingResult, EnrollmentConsent, EnrollmentResult)

class SpeakerError(Exception):
    def __init__(self, code="unavailable"):
        self.code = code if code in {"unavailable", "invalid_profile", "invalid_audio",
            "invalid_embedding", "cancelled", "incompatible_profile", "runtime_unavailable", "model_missing", "model_invalid", "inference_failed", "protection_unavailable", "protection_failed", "provisioning_failed", "consent_required", "calibration_pending"} else "unavailable"
        super().__init__(self.code)

class SpeakerEmbeddingEngine(Protocol):
    identity: ModelIdentity
    def extract(self, audio: RecordedAudio, *, cancel: Event | None = None): ...

class BiometricProtector(Protocol):
    def protect(self, plaintext: bytes) -> bytes: ...
    def unprotect(self, ciphertext: bytes) -> bytes: ...

class SpeakerProfileRepository(Protocol):
    def load(self, profile_id: UUID) -> SpeakerProfile: ...
    def save(self, profile: SpeakerProfile, *, cancel: Event | None = None) -> None: ...
    def delete(self, profile_id: UUID) -> None: ...
    def list_ids(self) -> tuple[UUID, ...]: ...

class AudioQualityAssessment(Protocol):
    def assess(self, audio: RecordedAudio) -> SpeakerQualitySummary: ...

class ThresholdPolicy(Protocol):
    configuration: ThresholdConfiguration
    def decide(self, score: float) -> str: ...

class AntiSpoofingBoundary(Protocol):
    def assess(self, audio: RecordedAudio) -> AntiSpoofingResult: ...

class EnrollmentBoundary(Protocol):
    def enroll(self, samples, consent: EnrollmentConsent, *, cancel=None, profile_id=None) -> EnrollmentResult: ...

class VerificationBoundary(Protocol):
    def verify(self, audio: RecordedAudio, profile_id: UUID, *, audio_id: UUID, cancel=None) -> VerificationResult: ...

class STTGatewayDependency(Protocol):
    def transcribe_audio(self, audio: RecordedAudio, *, audio_id: UUID, cancel=None): ...

class CommandResolutionDependency(Protocol):
    def resolve_stt(self, result): ...
