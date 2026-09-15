"""Current-user DPAPI envelope. Fake API injection keeps tests non-biometric."""
from app.speaker.contracts import SpeakerError
from app.speaker.windows import LIMIT

class DPAPIProtector:
    def __init__(self, *, api_factory=None):
        self.factory = api_factory
        self._api = None

    def _get_api(self):
        try:
            if self._api is None:
                if self.factory is None:
                    from app.speaker.windows import WindowsAPI
                    self._api = WindowsAPI()
                else:
                    self._api = self.factory()
            return self._api
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("protection_unavailable") from None

    def _convert(self, data, decrypt):
        if not isinstance(data, bytes) or not 0 < len(data) <= LIMIT:
            raise SpeakerError("protection_failed")
        try:
            result = self._get_api().crypt_bytes(data,decrypt=decrypt)
            if not isinstance(result, bytes) or not 0 < len(result) <= LIMIT:
                raise SpeakerError("protection_failed")
            return result
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("protection_failed") from None

    def protect(self, plaintext):
        return self._convert(plaintext,False)

    def unprotect(self, ciphertext):
        return self._convert(ciphertext,True)

    def smoke(self):
        marker = b"VoicePilot non-biometric DPAPI smoke v1"
        if self.unprotect(self.protect(marker)) != marker:
            raise SpeakerError("protection_failed")
        return {"dpapi":"ready", "scope":"current-user", "biometric_data_used":False}
