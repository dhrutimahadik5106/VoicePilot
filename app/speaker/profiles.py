"""Explicit protected files; no imports create directories or load profiles."""
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID
from app.speaker.contracts import SpeakerError
from app.speaker.models import SpeakerProfile

MAX_BYTES = 131072
REPO = Path(__file__).resolve().parents[2]

def default_profile_root():
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise SpeakerError("unavailable")
    return Path(value) / "VoicePilot" / "speaker-profiles"

def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise SpeakerError("cancelled")

def identifier(value):
    if not isinstance(value, UUID):
        raise SpeakerError("invalid_profile")
    return str(value)

class ProtectedProfileRepository:
    """Caller must provision a private directory and audited protector explicitly.

    Does not create roots, manage keys, cache templates, or supply a real protector.
    Protectors are trusted dependencies, never chosen from profile file contents.
    """
    def __init__(self, root, protector):
        self.root = Path(root)
        self.protector = protector

    def _root(self):
        try:
            root = self.root
            if not root.is_absolute() or not root.is_dir():
                raise ValueError()
            for part in (root, *root.parents):
                if part.is_symlink() or part.is_junction():
                    raise ValueError()
            resolved = root.resolve(strict=True)
            if resolved.is_relative_to(REPO):
                raise ValueError()
            return resolved
        except Exception:
            raise SpeakerError("invalid_profile") from None

    def _path(self, profile_id):
        name = identifier(profile_id) + ".speaker-profile"
        path = self._root() / name
        if path.is_symlink() or path.is_junction():
            raise SpeakerError("invalid_profile")
        if path.exists() and not path.is_file():
            raise SpeakerError("invalid_profile")
        return path

    def load(self, profile_id):
        try:
            path = self._path(profile_id)
            with path.open("rb") as source:
                sealed = source.read(MAX_BYTES + 1)
            if not sealed or len(sealed) > MAX_BYTES:
                raise ValueError()
            plaintext = self.protector.unprotect(sealed)
            if not isinstance(plaintext, bytes) or len(plaintext) > MAX_BYTES:
                raise ValueError()
            # Explicit private decoding; never return payload in error text.
            document = json.loads(plaintext)
            profile = SpeakerProfile.model_validate(document)
            if profile.profile_id != profile_id:
                raise ValueError()
            return profile
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("invalid_profile") from None

    def save(self, profile, *, cancel=None):
        temporary = None
        try:
            check_cancel(cancel)
            profile = SpeakerProfile.model_validate(profile.model_dump() | {"template": profile.template})
            path = self._path(profile.profile_id)
            # This is the sole privileged template serializer.
            document = profile.model_dump(mode="json") | {"template": profile.template.tolist()}
            plaintext = json.dumps(document, allow_nan=False, separators=(",", ":")).encode()
            if len(plaintext) > MAX_BYTES:
                raise ValueError()
            sealed = self.protector.protect(plaintext)
            if not isinstance(sealed, bytes) or not sealed or len(sealed) > MAX_BYTES:
                raise ValueError()
            check_cancel(cancel)
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                    prefix=".speaker-", suffix=".tmp", delete=False) as destination:
                temporary = Path(destination.name)
                destination.write(sealed)
                destination.flush()
                os.fsync(destination.fileno())
            check_cancel(cancel)
            # Recheck destination/root before the atomic commit.
            if self._path(profile.profile_id) != path:
                raise ValueError()
            os.replace(temporary, path)
            temporary = None
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("unavailable") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Only protected bytes; root must be privately provisioned.

    def delete(self, profile_id):
        try:
            self._path(profile_id).unlink(missing_ok=True)
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("unavailable") from None

    def list_ids(self):
        try:
            identifiers = []
            for path in self._root().glob("*.speaker-profile"):
                value = UUID(path.stem)
                if str(value) != path.stem:
                    raise ValueError()
                self.load(value)  # Reject corruption; expose only validated opaque IDs.
                identifiers.append(value)
            return tuple(sorted(identifiers, key=str))
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("invalid_profile") from None
