"""UUID-only, protected diagnostic screenshot storage; no user-selected paths."""
import os
from pathlib import Path
import tempfile
from uuid import UUID, uuid4
from app.operations.capture import MAX_BYTES, validate_bmp
from app.operations.models import OperationError, Code


def diagnostic_root():
    import ctypes as c
    from ctypes import wintypes as w
    from app.operations.windows import dll, function, guid, GUID, P
    shell, ole = dll("shell32.dll"), dll("ole32.dll")
    folder = guid("f1b32785-6fba-4fcf-9d55-7b8e7f157091")
    value = P()
    hr = function(shell, "SHGetKnownFolderPath", c.c_long, c.POINTER(GUID), w.DWORD, P,
                  c.POINTER(P))(c.byref(folder), 0, None, c.byref(value))
    if hr < 0:
        raise OperationError(Code.DENIED)
    try:
        return Path(c.wstring_at(value)) / "VoicePilot" / "diagnostics" / "screenshots"
    finally:
        function(ole, "CoTaskMemFree", None, P)(value)


class ScreenshotStore:
    def __init__(self, *, root=None, protector=None):
        # Dependency injection is for trusted temporary-directory tests, never CLI/config.
        self._root, self._protector = root, protector

    def root(self):
        try:
            from app.speaker.private_store import private_root
            root = Path(self._root) if self._root is not None else diagnostic_root()
            if str(root).startswith(("//", chr(92) * 2)):
                raise ValueError()
            return private_root(root)
        except Exception:
            raise OperationError(Code.DENIED) from None

    def path(self, key):
        if type(key) is not UUID:
            raise OperationError(Code.INVALID)
        path = self.root() / (str(key) + ".vp-screen.bmp")
        if path.is_symlink() or path.is_junction():
            raise OperationError(Code.DENIED)
        if path.exists() and path.stat().st_nlink != 1:
            raise OperationError(Code.DENIED)
        return path

    def save(self, data, *, guard):
        validate_bmp(data)
        temporary = None
        try:
            guard()
            root = self.root()
            root.mkdir(parents=True, exist_ok=True)
            self.root()
            if self._protector is None:
                from app.speaker.windows import WindowsAPI
                protector = WindowsAPI().restrict_directory
            else:
                protector = self._protector
            protector(root)  # No private bytes written before restrictive ACL succeeds.
            key = uuid4()
            path = self.path(key)
            if path.exists():
                raise OperationError(Code.DENIED)
            with tempfile.NamedTemporaryFile(dir=root, prefix=".vp-screen-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            guard()
            self.path(key)
            os.link(temporary, path)  # Atomic no-overwrite publication.
            temporary.unlink()
            temporary = None
            return key
        except OperationError:
            raise
        except Exception:
            raise OperationError(Code.FAILED) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def verify(self, key):
        try:
            path = self.path(key)
            if not path.is_file() or not 54 < path.stat().st_size <= MAX_BYTES:
                raise OperationError(Code.UNVERIFIED)
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
            return validate_bmp(data)
        except OperationError:
            raise
        except Exception:
            raise OperationError(Code.NO_OBSERVATION) from None

    def exists(self, key):
        return self.path(key).exists()

    def delete(self, key, *, guard):
        try:
            path = self.path(key)
            if not path.is_file():
                raise OperationError(Code.INVALID)
            guard()
            path.unlink()
        except OperationError:
            raise
        except Exception:
            raise OperationError(Code.FAILED) from None
