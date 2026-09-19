from contextlib import contextmanager
from pathlib import PureWindowsPath
from app.launch.models import Discovery, LaunchError, LaunchPlan, ProcessObservation, Status
from app.launch.authorization import ManualAuthority

IDENTITY = "1" * 64


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class Backend:
    def __init__(self, clock=None):
        self.calls = []
        self.created = 0
        self.already = False
        self.match = True
        self.available = True
        self.discovery = Status.AVAILABLE
        self.changed = False
        self.error = None
        self.clock = clock or Clock()
        self.on_revalidate = lambda: None
        self.on_launch = lambda: None

    def discover(self, app, timeout):
        self.calls.append("discover")
        return Discovery(application_id=app, status=self.discovery,
                         identity=IDENTITY if self.discovery == Status.AVAILABLE else None)

    @contextmanager
    def revalidate(self, app, identity, timeout):
        self.calls.append("revalidate")
        self.on_revalidate()
        if self.changed or identity != IDENTITY:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        yield object()

    def launch(self, image):
        self.calls.append("launch")
        self.created += 1
        self.on_launch()
        if self.error:
            raise self.error
        return 123

    def observe(self, app, identity, timeout):
        self.calls.append("observe")
        self.clock.value += .02
        return ProcessObservation(application_id=app, identity=identity,
                                  matched=self.match and bool(self.created or self.already), available=self.available)


def grant(app="notepad", authority=None):
    authority = authority or ManualAuthority()
    plan = LaunchPlan(application_id=app, identity=IDENTITY)
    key = authority.challenge(plan, typed_application=app)
    permit = authority.confirm(key, plan, response="LAUNCH " + app)
    return plan, permit, authority


class NativeFake:
    def __init__(self):
        self.handles = {}
        self.closed = []
        self.calls = []
        self.version = 1
        self.bad_publisher = False
        self.bad_original = False
        self.reparse = False
        self.writable = False
        self.missing = False
        self.mismatch = False
        self.processes = []
        self.created = []

    def roots(self):
        return "C:/Windows/System32", ("C:/Program Files",)

    def attributes(self, path):
        self.calls.append("attributes")
        if self.missing and path.suffix == ".exe":
            raise LaunchError(Status.NOT_INSTALLED)
        return 0x400 if self.reparse else (0 if path.suffix.casefold() == ".exe" else 0x10)

    def lock(self, path, directory=False):
        handle = len(self.handles) + 1
        self.handles[handle] = str(path)
        self.calls.append("lock")
        return handle

    def close(self, handle):
        self.closed.append(handle)

    def final_path(self, handle):
        return "C:/untrusted/other.exe" if self.mismatch else self.handles[handle]

    def protected(self, handle):
        self.calls.append("protected")
        if self.writable:
            raise LaunchError(Status.IDENTITY_MISMATCH)

    def publisher(self, path, handle):
        self.calls.append("publisher")
        if self.bad_publisher:
            return "Untrusted Publisher"
        return {"chrome.exe": "Google LLC", "spotify.exe": "Spotify AB"}.get(path.name.casefold(), "Microsoft Corporation")

    def original_name(self, path):
        return "other.exe" if self.bad_original else path.name

    def file_identity(self, handle):
        return (1, 2, 3, self.version)

    def create_process(self, path, directory):
        self.calls.append("create_process")
        self.created.append((path, directory))
        return 123

    def process_paths(self):
        return self.processes
