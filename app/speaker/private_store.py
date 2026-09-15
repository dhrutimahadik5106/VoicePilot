"""Explicit private DPAPI records outside repository and known sync roots."""
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID
from app.speaker.contracts import SpeakerError
from app.speaker.profiles import REPO, check_cancel
from app.speaker.dpapi import DPAPIProtector

def private_root(path):
    try:
        path = Path(path)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError()
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise ValueError()
        resolved = path.resolve()
        excluded = [REPO]
        for key in ("OneDrive","OneDriveConsumer","OneDriveCommercial"):
            if os.environ.get(key):
                excluded.append(Path(os.environ[key]).resolve())
        if any(resolved.is_relative_to(root) for root in excluded):
            raise ValueError()
        if any("onedrive" in part.lower() for part in path.parts):
            raise ValueError()
        return resolved
    except Exception:
        raise SpeakerError("invalid_profile") from None

def provision_private_root(path, *, api=None):
    root = private_root(path)
    if api is None:
        from app.speaker.windows import WindowsAPI
        api = WindowsAPI()
    # Empty directory may briefly inherit ACLs; no private data is written until
    # restriction succeeds. Never modifies ancestors' ACLs.
    root.mkdir(parents=True,exist_ok=True)
    private_root(root)
    api.restrict_directory(root)
    return root

class PrivateRecords:
    def __init__(self, root, protector=None):
        self.root = private_root(root)
        self.protector = protector or DPAPIProtector()

    def _path(self, identifier):
        if not isinstance(identifier,UUID):
            raise SpeakerError("invalid_profile")
        root = private_root(self.root)
        path = root / (str(identifier)+".speaker-private")
        if not root.is_dir() or path.is_symlink() or path.is_junction():
            raise SpeakerError("invalid_profile")
        return path

    def save(self, identifier, document, *, cancel=None):
        temporary = None
        try:
            check_cancel(cancel)
            path = self._path(identifier)
            if path.exists():  # append-only trials/frozen policies; no silent edits
                raise SpeakerError("invalid_profile")
            plaintext = json.dumps(document,allow_nan=False,separators=(",",":")).encode()
            sealed = self.protector.protect(plaintext)
            with tempfile.NamedTemporaryFile(dir=self.root,prefix=".private-",suffix=".tmp",delete=False) as output:
                temporary=Path(output.name)
                output.write(sealed)
                output.flush()
                os.fsync(output.fileno())
            check_cancel(cancel)
            self._path(identifier)
            os.rename(temporary,path)
            temporary=None
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("protection_failed") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass  # Never expose private paths in cleanup errors.

    def load(self, identifier):
        try:
            with self._path(identifier).open("rb") as stream:
                sealed=stream.read(131073)
            if not 0 < len(sealed) <= 131072:
                raise ValueError()
            raw=self.protector.unprotect(sealed)
            if not 0 < len(raw) <= 131072:
                raise ValueError()
            return json.loads(raw)
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("invalid_profile") from None

    def ids(self):
        try:
            root=private_root(self.root)
            return tuple(UUID(p.stem) for p in root.glob("*.speaker-private"))
        except Exception:
            raise SpeakerError("invalid_profile") from None
