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
        self._notepad_attempt = None

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

    def launch(self, image, *, guard=lambda: None):
        if type(image) is not ValidatedImage:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        system, _ = self.native.roots()
        if image.path == PureWindowsPath(system) / "notepad.exe":
            from app.launch.notepad import CreatedProcess, NotepadAttempt
            self.finish_notepad()
            baseline = frozenset((p.pid, p.created) for p in self.native.notepad_processes())
            package_expected = self.native.notepad_package_registered()
            guard()
            started = self.clock()
            process = self.native.create_process(image.path, system, retain=True)
            if type(process) is not CreatedProcess or process.created <= 0:
                raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
            self._notepad_attempt = NotepadAttempt(baseline, process, started, package_expected)
            return process.pid
        guard()
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
        if application_id == "notepad":
            return self.observe_notepad(identity, timeout)
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


    def finish_notepad(self):
        attempt, self._notepad_attempt = self._notepad_attempt, None
        if attempt is not None:
            self.native.close(attempt.process.handle)  # Release handle; never terminate the process.

    @contextmanager
    def validate_notepad_process(self, record, identity):
        """Separate final-package identity from the unchanged system-launcher identity."""
        from app.launch.notepad import FAMILY, AUMID, PACKAGE_PATTERN, NotepadProcess
        if type(record) is not NotepadProcess:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        path = PureWindowsPath(record.path)
        system, programs = self.native.roots()
        if path == PureWindowsPath(system) / "notepad.exe":
            if record.package or record.family or record.aumid:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            with self.validate_image("notepad", path, PureWindowsPath(system)) as image:
                if image.identity != identity:
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                yield "legacy_system"
            return
        if (record.family != FAMILY or record.aumid != AUMID
                or re.fullmatch(PACKAGE_PATTERN, record.package) is None):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        registered = PureWindowsPath(self.native.package_path(record.package))
        program = next((PureWindowsPath(p) for p in programs
                        if registered == PureWindowsPath(p) / "WindowsApps" / record.package), None)
        if program is None or path != registered / "Notepad" / "Notepad.exe":
            raise LaunchError(Status.IDENTITY_MISMATCH)
        validate_path(str(path), str(registered), ("notepad.exe",))
        # WindowsApps deliberately denies container opens to standard users. Trust
        # Windows' exact registered package location, then verify/hold the package
        # root and descendants themselves, plus its protected Program Files anchor.
        with ExitStack() as stack:
            for item in (program, registered, registered / "Notepad", path):
                attrs = self.native.attributes(item)
                if attrs & 0x400 or bool(attrs & 0x10) != (item != path):
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                handle = self.native.lock(item, directory=item != path)
                stack.callback(self.native.close, handle)
                if PureWindowsPath(self.native.final_path(handle)) != item:
                    raise LaunchError(Status.IDENTITY_MISMATCH)
                self.native.protected(handle, package=item != program)
            if self.native.publisher(path, handle) not in ALLOWLIST["notepad"].publishers:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            # Package identity + exact signed executable replace legacy MUI metadata
            # for observation only. No new executable launch target is introduced.
            yield "protected_notepad_package"

    def observe_notepad(self, identity, timeout):
        result = dict(application_id="notepad", identity=identity, matched=False)
        attempt = self._notepad_attempt
        if attempt is None:
            return ProcessObservation(**result)
        start = self.clock()
        for record in self.native.notepad_processes():
            if self.clock() - start >= timeout:
                raise LaunchError(Status.TIMED_OUT)
            if not attempt.correlates(record):
                continue
            elapsed = self.clock() - attempt.started
            if elapsed < 0 or (record.created - attempt.process.created) / 10_000_000 > elapsed + .001:
                continue
            with self.validate_notepad_process(record, identity) as classification:
                if attempt.package_expected and classification == "legacy_system":
                    continue  # The system broker is not the final modern application.
                # Recheck liveness and start-time identity after filesystem/signature work.
                current = self.native.notepad_processes()
                still_live = any((p.pid, p.parent_pid, p.created, p.path, p.family, p.package, p.aumid)
                    == (record.pid, record.parent_pid, record.created, record.path, record.family, record.package, record.aumid)
                    for p in current)
                if self.clock() - start >= timeout:
                    raise LaunchError(Status.TIMED_OUT)
                if still_live:
                    result["matched"] = True
                    return ProcessObservation(**result)
        return ProcessObservation(**result)

    def notepad_diagnostics(self):
        """Read-only, allowlisted report; no raw paths, titles or command lines."""
        from datetime import datetime, timezone
        from app.launch.notepad import FAMILY, AUMID
        discovery = self.discover("notepad", 5)
        reports = []
        start = self.clock()
        for record in self.native.notepad_processes():
            if self.clock() - start >= 5:
                raise LaunchError(Status.TIMED_OUT)
            classification, valid = "unverified", False
            try:
                with self.validate_notepad_process(record, discovery.identity) as classification:
                    valid = True
            except LaunchError:
                classification = "unverified"
            reports.append({"pid": record.pid, "filename": "notepad.exe",
                "location": classification, "identity_validated": valid,
                "publisher_validation": "verified_microsoft" if valid else "not_verified",
                "package_family": FAMILY if record.family == FAMILY else "not_approved_or_absent",
                "application_identity": AUMID if record.aumid == AUMID else "not_approved_or_absent",
                "created_filetime": record.created, "launch_correlation": "not_available_read_only"})
        return {"mode": "read_only_notepad_identity", "timestamp": datetime.now(timezone.utc).isoformat(),
                "processes": reports, "execution_permitted": False}
