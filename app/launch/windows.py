"""Fixed candidate discovery, held identity validation and independent OS observation."""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PureWindowsPath
from time import monotonic
import re

from app.launch.allowlist import ALLOWLIST, validate_path
from app.launch.models import Discovery, LaunchError, Status, ProcessObservation


@dataclass(frozen=True, repr=False)
class ValidatedImage:
    path: PureWindowsPath
    root: PureWindowsPath
    identity: str
    handle: object


class WindowsBackend:
    def __init__(self, *, native=None, clock=monotonic):
        self._native = native
        self.clock = clock

    @property
    def native(self):
        if self._native is None:
            from app.launch.winapi import Native
            self._native = Native()
        return self._native

    def candidates(self, application_id):
        if application_id not in ALLOWLIST:
            raise LaunchError(Status.UNSUPPORTED)
        system, programs = self.native.roots()
        if application_id in {"notepad", "calculator"}:
            name = "notepad.exe" if application_id == "notepad" else "calc.exe"
            return ((PureWindowsPath(system) / name, PureWindowsPath(system)),)
        relative = ("Google", "Chrome", "Application", "chrome.exe") if application_id == "chrome" else ("Spotify", "Spotify.exe")
        return tuple((PureWindowsPath(root).joinpath(*relative), PureWindowsPath(root)) for root in programs)

    @contextmanager
    def validate_image(self, application_id, path, root):
        entry = ALLOWLIST[application_id]
        path = validate_path(str(path), str(root), entry.executable_names)
        root = PureWindowsPath(root)
        parents = [root]
        for part in path.relative_to(root).parts[:-1]:
            parents.append(parents[-1] / part)
        with ExitStack() as stack:
            for item in (*parents, path):
                attrs = self.native.attributes(item)
                if attrs & 0x400 or bool(attrs & 0x10) != (item != path):
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                handle = self.native.lock(item, directory=item != path)
                stack.callback(self.native.close, handle)
                canonical = PureWindowsPath(self.native.final_path(handle))
                if canonical != item:
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                self.native.protected(handle)
            publisher = self.native.publisher(path, handle)
            if publisher not in entry.publishers or self.native.original_name(path).casefold() not in {n.casefold() for n in entry.original_filenames}:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            identity = sha256(repr((str(path).casefold(), self.native.file_identity(handle), publisher)).encode()).hexdigest()
            yield ValidatedImage(path, root, identity, handle)

    def discover(self, application_id, timeout):
        start = self.clock()
        failure = Status.NOT_INSTALLED
        try:
            for path, root in self.candidates(application_id):
                if self.clock() - start >= timeout:
                    return Discovery(application_id=application_id, status=Status.TIMED_OUT)
                try:
                    with self.validate_image(application_id, path, root) as image:
                        if self.clock() - start >= timeout:
                            return Discovery(application_id=application_id, status=Status.TIMED_OUT)
                        return Discovery(application_id=application_id, status=Status.AVAILABLE, identity=image.identity)
                except LaunchError as error:
                    if error.status != Status.NOT_INSTALLED:
                        failure = error.status
            return Discovery(application_id=application_id, status=failure)
        except LaunchError as error:
            return Discovery(application_id=application_id, status=error.status)
        except Exception:
            return Discovery(application_id=application_id, status=Status.IDENTITY_MISMATCH)

    @contextmanager
    def revalidate(self, application_id, identity, timeout):
        start = self.clock()
        for path, root in self.candidates(application_id):
            with ExitStack() as stack:
                try:
                    image = stack.enter_context(self.validate_image(application_id, path, root))
                except LaunchError as error:
                    if error.status == Status.NOT_INSTALLED:
                        continue
                    raise
                if self.clock() - start >= timeout:
                    raise LaunchError(Status.TIMED_OUT)
                if image.identity != identity:
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                # Keep all locks held; caller failures must never select another candidate.
                yield image
                return
        raise LaunchError(Status.NOT_INSTALLED)

    def launch(self, image):
        if type(image) is not ValidatedImage:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        system, _ = self.native.roots()
        return self.native.create_process(image.path, system)

    def packaged_root(self, application_id, path):
        """Recognize only two Microsoft package identities; never activate an AUMID/URI."""
        if application_id not in {"notepad", "calculator"}:
            return None
        _, programs = self.native.roots()
        package = "Microsoft.WindowsCalculator" if application_id == "calculator" else "Microsoft.WindowsNotepad"
        expected_tail = ("CalculatorApp.exe",) if application_id == "calculator" else ("Notepad", "Notepad.exe")
        for program in programs:
            root = PureWindowsPath(program) / "WindowsApps"
            if not path.is_relative_to(root):
                continue
            parts = path.relative_to(root).parts
            if (len(parts) == len(expected_tail) + 1
                    and tuple(p.casefold() for p in parts[1:]) == tuple(p.casefold() for p in expected_tail)
                    and re.fullmatch(re.escape(package) + r"_[0-9.]+_(?:x64|x86|arm64)__8wekyb3d8bbwe", parts[0], re.I)):
                return root
        return None

    def observe(self, application_id, identity, timeout):
        start = self.clock()
        paths = {path: root for path, root in self.candidates(application_id)}
        for pid, text in self.native.process_paths():
            if self.clock() - start >= timeout:
                raise LaunchError(Status.TIMED_OUT)
            path = PureWindowsPath(text)
            packaged = None if path in paths else self.packaged_root(application_id, path)
            root = paths.get(path, packaged)
            if root is None:
                continue
            with self.validate_image(application_id, path, root) as image:
                if self.clock() - start >= timeout:
                    raise LaunchError(Status.TIMED_OUT)
                # Store apps may run behind the fixed, signed system executable.
                # A fixed package identity plus independently verified publisher/name is required.
                if image.identity == identity or packaged is not None:
                    return ProcessObservation(application_id=application_id, identity=identity, matched=True)
        return ProcessObservation(application_id=application_id, identity=identity, matched=False)
