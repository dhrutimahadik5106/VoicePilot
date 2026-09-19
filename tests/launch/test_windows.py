from pathlib import PureWindowsPath
import pytest
from app.launch.models import LaunchError, Status
from app.launch.windows import WindowsBackend
from tests.launch.helpers import NativeFake


@pytest.mark.parametrize("app", ["notepad", "calculator", "chrome", "spotify"])
def test_safe_discovery_never_launches(app):
    native = NativeFake()
    backend = WindowsBackend(native=native)
    result = backend.discover(app, 5)
    assert result.status == Status.AVAILABLE
    assert "identity" not in result.model_dump_json() + repr(result)
    assert native.created == [] and native.closed


@pytest.mark.parametrize("fault", ["bad_publisher", "bad_original", "reparse", "writable", "mismatch"])
def test_identity_checks_fail_closed(fault):
    native = NativeFake()
    setattr(native, fault, True)
    result = WindowsBackend(native=native).discover("notepad", 5)
    assert result.status == Status.IDENTITY_MISMATCH and native.created == []


def test_missing_installation():
    native = NativeFake()
    native.missing = True
    assert WindowsBackend(native=native).discover("spotify", 5).status == Status.NOT_INSTALLED


def test_immediate_revalidation_and_handles_held():
    native = NativeFake()
    backend = WindowsBackend(native=native)
    initial = backend.discover("chrome", 5)
    with backend.revalidate("chrome", initial.identity, 5) as image:
        assert image.handle not in native.closed
        backend.launch(image)
        assert image.handle not in native.closed
    assert image.handle in native.closed and len(native.created) == 1
    assert native.created[0][0] == PureWindowsPath("C:/Program Files/Google/Chrome/Application/chrome.exe")
    assert native.created[0][1] == "C:/Windows/System32"


def test_changed_image_never_launched():
    native = NativeFake()
    backend = WindowsBackend(native=native)
    initial = backend.discover("notepad", 5)
    native.version += 1
    with pytest.raises(LaunchError):
        with backend.revalidate("notepad", initial.identity, 5):
            pytest.fail("changed_image_admitted")
    assert native.created == []


def test_independent_process_observation():
    native = NativeFake()
    backend = WindowsBackend(native=native)
    initial = backend.discover("notepad", 5)
    assert not backend.observe("notepad", initial.identity, 5).matched
    native.processes = [(12, "C:/Windows/System32/notepad.exe")]
    assert backend.observe("notepad", initial.identity, 5).matched
    native.version += 1
    assert not backend.observe("notepad", initial.identity, 5).matched


@pytest.mark.parametrize("path", ["C:/Users/Fictional/notepad.exe", "//host/share/notepad.exe",
    "C:/Program Files/WindowsApps/Other_1.0_x64__8wekyb3d8bbwe/CalculatorApp.exe",
    "C:/Program Files/WindowsApps/Microsoft.WindowsCalculator_1.0_x64__other/CalculatorApp.exe"])
def test_untrusted_process_paths_not_read(path):
    native = NativeFake()
    native.processes = [(12, path)]
    backend = WindowsBackend(native=native)
    assert not backend.observe("calculator", "1" * 64, 5).matched
    assert native.calls == []


@pytest.mark.parametrize("app,tail", [
    ("calculator", "Microsoft.WindowsCalculator_1.0.0.0_x64__8wekyb3d8bbwe/CalculatorApp.exe"),
    ("notepad", "Microsoft.WindowsNotepad_1.0.0.0_x64__8wekyb3d8bbwe/Notepad/Notepad.exe")])
def test_fixed_package_identity_observed(app, tail):
    native = NativeFake()
    native.processes = [(12, "C:/Program Files/WindowsApps/" + tail)]
    assert WindowsBackend(native=native).observe(app, "1" * 64, 5).matched
    assert "publisher" in native.calls and not native.created


@pytest.mark.parametrize("metadata,accepted", [("NOTEPAD.EXE.MUI", True),
    ("notepad.exe.mui.exe", False), ("other.exe.mui", False)])
def test_exact_notepad_metadata_only(metadata, accepted):
    from app.launch.allowlist import ALLOWLIST, validate_path
    native = NativeFake()
    native.original_name = lambda path: metadata
    result = WindowsBackend(native=native).discover("notepad", 5)
    assert (result.status == Status.AVAILABLE) is accepted
    assert ALLOWLIST["notepad"].executable_names == ("notepad.exe",)
    with pytest.raises(LaunchError):
        validate_path("C:/Windows/System32/notepad.exe.mui", "C:/Windows/System32",
                      ALLOWLIST["notepad"].executable_names)
    assert not native.created
