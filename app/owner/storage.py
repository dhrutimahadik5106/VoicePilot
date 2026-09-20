"""Atomic current-user protected owner summaries; existing profiles are unchanged."""
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID
from app.owner.models import Record, OwnerError
from app.speaker.private_store import private_root, provision_private_root
from app.speaker.dpapi import DPAPIProtector

LIMIT = 131072


def default_root():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OwnerError("storage_failed")
    return Path(local) / "VoicePilot" / "owner-calibration"


class Store:
    def __init__(self, root=None, *, protector=None, provisioner=provision_private_root):
        self.root = root
        self.protector = protector or DPAPIProtector()
        self.provisioner = provisioner

    def path(self, profile_id):
        try:
            if type(profile_id) is not UUID:
                raise ValueError()
            root = private_root(self.root if self.root is not None else default_root())
            if str(root).startswith(("//", chr(92) * 2)):
                raise ValueError()
            path = root / (str(profile_id) + ".owner-calibration")
            if path.is_symlink() or path.is_junction() or path.exists() and path.stat().st_nlink != 1:
                raise ValueError()
            return path
        except Exception:
            raise OwnerError("storage_failed") from None

    def load(self, profile_id):
        try:
            path = self.path(profile_id)
            if not path.exists():
                raise OwnerError("calibration_required")
            with path.open("rb") as source:
                sealed = source.read(LIMIT + 1)
            if not 0 < len(sealed) <= LIMIT:
                raise ValueError()
            raw = self.protector.unprotect(sealed)
            if not 0 < len(raw) <= LIMIT:
                raise ValueError()
            record = Record.model_validate(json.loads(raw))
            if record.private.get("profile") != str(profile_id):
                raise ValueError()
            return record
        except OwnerError:
            raise
        except Exception:
            raise OwnerError("profile_corrupt") from None

    def save(self, profile_id, record, *, previous=None):
        temporary = None
        try:
            path = self.path(profile_id)
            if previous is not None and self.load(profile_id).private.get("revision") != previous:
                raise OwnerError("concurrent_update")
            self.provisioner(path.parent)
            raw = json.dumps(record.document(), allow_nan=False, separators=(",", ":")).encode()
            if not 0 < len(raw) <= LIMIT:
                raise ValueError()
            sealed = self.protector.protect(raw)
            if not 0 < len(sealed) <= LIMIT:
                raise ValueError()
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".owner-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(sealed)
                stream.flush()
                os.fsync(stream.fileno())
            self.path(profile_id)
            if previous is not None and self.load(profile_id).private.get("revision") != previous:
                raise OwnerError("concurrent_update")
            os.replace(temporary, path)
            temporary = None
        except OwnerError:
            raise
        except Exception:
            raise OwnerError("storage_failed") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def delete(self, profile_id):
        try:
            self.path(profile_id).unlink(missing_ok=True)
        except Exception:
            raise OwnerError("storage_failed") from None
