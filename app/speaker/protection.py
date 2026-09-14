"""Secure persistence boundary. No plaintext fallback or untested DPAPI implementation."""
from app.speaker.contracts import SpeakerError

class UnavailableBiometricProtector:
    """Future adapter: Windows current-user DPAPI with restrictive ACL provisioning.

    Phase 4A deliberately supplies no real protector. Runtime availability alone
    must never cause an automatic switch to persistent biometric storage.
    """
    def protect(self, plaintext):
        raise SpeakerError("unavailable")
    def unprotect(self, ciphertext):
        raise SpeakerError("unavailable")
