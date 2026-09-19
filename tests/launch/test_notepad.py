from pathlib import PureWindowsPath
from threading import Event
import json
import pytest
from app.launch.authorization import ManualAuthority
from app.launch.cli import main
from app.launch.controller import LaunchController
from app.launch.models import LaunchError, LaunchPlan, Status
from app.launch.notepad import AUMID, FAMILY, CreatedProcess, NotepadProcess
from app.launch.windows import WindowsBackend
from tests.launch.helpers import Clock, NativeFake

PACKAGE = "Microsoft.WindowsNotepad_11.1.2.3_x64__8wekyb3d8bbwe"
ROOT = "C:/Program Files/WindowsApps/" + PACKAGE
CREATED = 100_000_000


def record(**changes):
    fields = dict(pid=101, parent_pid=100, created=CREATED + 50_000,
                  path=ROOT + "/Notepad/Notepad.exe", family=FAMILY,
                  package=PACKAGE, aumid=AUMID)
    return NotepadProcess(**(fields | changes))


class NativeNotepad(NativeFake):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.before = ()
        self.after = (record(),)
        self.launched = False
        self.delay = 0
        self.signature_bad = False
        self.publisher_bad = False
        self.registered = ROOT
        self.package_expected = True
        self.on_create = lambda: None

    def notepad_processes(self):
        if self.launched:
            self.clock.value += self.delay
        return self.after if self.launched else self.before

    def notepad_package_registered(self):
        return self.package_expected

    def package_path(self, name):
        return self.registered

    def publisher(self, path, handle):
        if "WindowsApps" in path.parts:
            if self.signature_bad:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            if self.publisher_bad:
                return "Untrusted Publisher"
        return super().publisher(path, handle)

    def original_name(self, path):
        assert "WindowsApps" not in path.parts, "package_must_not_use_launcher_metadata"
        return super().original_name(path)

    def create_process(self, path, directory, *, retain=False):
        assert path == PureWindowsPath("C:/Windows/System32/notepad.exe")
        assert retain
        self.created.append((path, directory))
        self.launched = True
        self.clock.value += .01
        self.on_create()
        return CreatedProcess(100, CREATED, 999)


@pytest.fixture
def setup(monkeypatch):
    clock = Clock()
    native = NativeNotepad(clock)
    backend = WindowsBackend(native=native, clock=clock)
    def wait(event, duration=None):
        clock.value += duration or 0
        return event.is_set()
    monkeypatch.setattr(Event, "wait", wait)
    return native, backend, clock


def run(setup):
    native, backend, clock = setup
    discovery = backend.discover("notepad", 5)
    plan = LaunchPlan(application_id="notepad", identity=discovery.identity)
    authority = ManualAuthority()
    key = authority.challenge(plan, typed_application="notepad")
    permit = authority.confirm(key, plan, response="LAUNCH notepad")
    return LaunchController(backend=backend, clock=clock).run(plan, permit, authority)


@pytest.mark.parametrize("kind", ["legacy_original_pid", "packaged_original_pid",
                                  "modern_handoff", "launcher_exited"])
def test_verified_correlated_identity(setup, kind):
    native, backend, clock = setup
    if kind == "legacy_original_pid":
        native.package_expected = False
        native.after = (record(pid=100, created=CREATED, path="C:/Windows/System32/notepad.exe",
                               family="", package="", aumid=""),)
    elif kind == "packaged_original_pid":
        native.after = (record(pid=100, created=CREATED),)
    # Handoff records deliberately omit the launcher: it need not remain alive.
    result = run(setup)
    assert result.status == Status.LAUNCHED and result.process_observed
    assert len(native.created) == 1 and 999 in native.closed
    assert backend._notepad_attempt is None


@pytest.mark.parametrize("kind", ["preexisting", "unrelated_new", "pid_reused", "wrong_family",
    "similar_family", "similar_package", "similar_executable", "wrong_aumid", "untrusted_path",
    "network_path", "wrong_registered_root", "wrong_publisher", "wrong_signature", "no_final",
    "late_handoff", "future_timestamp", "writable_package", "reparse_package"])
def test_no_false_success(setup, kind):
    native, backend, clock = setup
    change = {
        "wrong_family": {"family": "Other_8wekyb3d8bbwe"},
        "similar_family": {"family": FAMILY + "Other"},
        "similar_package": {"package": PACKAGE + "Other"},
        "similar_executable": {"path": ROOT + "/Notepad/NotepadHelper.exe"},
        "wrong_aumid": {"aumid": FAMILY + "!Other"},
        "untrusted_path": {"path": "C:/Users/PRIVATE_MARKER/notepad.exe"},
        "network_path": {"path": "//PRIVATE_MARKER/share/notepad.exe"},
        "unrelated_new": {"parent_pid": 777},
        "pid_reused": {"pid": 100, "created": CREATED + 1},
        "future_timestamp": {"created": CREATED + 90_000_000},
    }.get(kind)
    if change:
        native.after = (record(**change),)
    elif kind == "preexisting":
        native.before = native.after = (record(pid=222, parent_pid=777, created=CREATED - 100),)
    elif kind == "wrong_registered_root":
        native.registered = "C:/Users/PRIVATE_MARKER/" + PACKAGE
    elif kind == "wrong_publisher":
        native.publisher_bad = True
    elif kind == "wrong_signature":
        native.signature_bad = True
    elif kind == "no_final":
        native.after = ()
    elif kind == "late_handoff":
        native.delay = 5.1
    elif kind == "writable_package":
        native.on_create = lambda: setattr(native, "writable", True)
    elif kind == "reparse_package":
        native.on_create = lambda: setattr(native, "reparse", True)
    result = run(setup)
    assert result.status not in {Status.LAUNCHED, Status.ALREADY_RUNNING}
    assert result.process_creation_attempted and not result.process_observed
    assert len(native.created) == 1 and 999 in native.closed
    assert not result.rollback_attempted
    assert "PRIVATE_MARKER" not in repr(result) + result.model_dump_json()


def test_preexisting_never_skips_new_launch(setup):
    native, backend, clock = setup
    native.before = (record(pid=222, parent_pid=777, created=CREATED - 100),)
    native.after = native.before + (record(),)
    assert run(setup).status == Status.LAUNCHED
    assert len(native.created) == 1


def test_diagnostic_privacy_and_no_launch(setup):
    native, backend, clock = setup
    native.before = (record(path="C:/Users/PRIVATE_MARKER/notepad.exe", family="PRIVATE_MARKER",
                            package="PRIVATE_MARKER", aumid="PRIVATE_MARKER"), record())
    output = []
    assert main(["diagnose-notepad"], backend=backend, write=output.append,
                read=lambda _: pytest.fail("diagnostic_prompted")) == 0
    text = "".join(output)
    assert "PRIVATE_MARKER" not in text and "C:/" not in text
    document = json.loads(text)
    assert not document["execution_permitted"] and not native.created
    assert document["processes"][1]["identity_validated"]
    assert document["processes"][1]["launch_correlation"] == "not_available_read_only"
    assert "PRIVATE_MARKER" not in repr(native.before[0]) + native.before[0].model_dump_json()


def test_no_launch_receipt_never_observed(setup):
    native, backend, clock = setup
    native.before = (record(),)
    assert not backend.observe("notepad", "1" * 64, 5).matched
    assert not native.created


def test_modern_launcher_alone_is_not_final_application(setup):
    native, backend, clock = setup
    native.after = (record(pid=100, created=CREATED, path="C:/Windows/System32/notepad.exe",
                           family="", package="", aumid=""),)
    result = run(setup)
    assert not result.process_observed and result.status == Status.VERIFICATION_FAILED


def test_final_process_disappearing_during_validation_is_not_success(setup):
    native, backend, clock = setup
    original = native.publisher
    def signature(path, handle):
        result = original(path, handle)
        if "WindowsApps" in path.parts:
            native.after = ()
        return result
    native.publisher = signature
    result = run(setup)
    assert not result.process_observed and result.status == Status.VERIFICATION_FAILED


def test_baseline_query_timeout_blocks_native_creation(setup):
    native, backend, clock = setup
    def delayed_registration():
        clock.value += 5.1
        return True
    native.notepad_package_registered = delayed_registration
    result = run(setup)
    assert result.status == Status.TIMED_OUT and not result.process_observed
    assert not native.created
