import ctypes as C
from types import SimpleNamespace
import pytest
from app.launch import winapi
from app.launch.models import LaunchError, Status


def native():
    value = object.__new__(winapi.Native)
    value.kernel = value.trust = value.crypto = value.security = object()
    value.closed = []
    value.close = value.closed.append
    return value


@pytest.mark.parametrize("succeeds", [True, False])
def test_create_process_exact_arguments_and_cleanup(monkeypatch, succeeds):
    api = native()
    calls = []
    api._check_not_elevated = lambda: calls.append("elevation_checked")
    def create(*args):
        assert calls == ["elevation_checked"]
        assert args[:8] == ("C:/Windows/System32/notepad.exe", None, None, None,
                            False, 0, None, "C:/Windows/System32")
        process = C.cast(args[9], C.POINTER(winapi.ProcessInfo)).contents
        process.pid, process.process, process.thread = 123, 11, 12
        return succeeds
    def function(library, name, *signature):
        assert name == "CreateProcessW"
        return create
    monkeypatch.setattr(winapi, "function", function)
    if succeeds:
        assert api.create_process("C:/Windows/System32/notepad.exe", "C:/Windows/System32") == 123
        assert api.closed == [12, 11]
    else:
        with pytest.raises(LaunchError):
            api.create_process("C:/Windows/System32/notepad.exe", "C:/Windows/System32")
        assert not api.closed


def test_elevated_token_blocks_creation(monkeypatch):
    api = native()
    def denied():
        raise LaunchError(Status.ACCESS_DENIED)
    api._check_not_elevated = denied
    monkeypatch.setattr(winapi, "function", lambda *a: pytest.fail("process_api_called"))
    with pytest.raises(LaunchError):
        api.create_process("unused", "unused")


@pytest.mark.parametrize("trust_result", [1, -1, 0])
def test_signature_fails_closed_and_closes_offline_trust_state(monkeypatch, trust_result):
    api = native()
    actions = []
    def verify(window, guid, pointer):
        data = C.cast(pointer, C.POINTER(winapi.TrustData)).contents
        actions.append(data.action)
        assert data.ui == 2 and data.flags == 0x3010
        return trust_result
    def function(library, name, *signature):
        if name == "WinVerifyTrust":
            return verify
        assert trust_result == 0 and name == "WTHelperProvDataFromStateData"
        return lambda *a: None
    monkeypatch.setattr(winapi, "function", function)
    with pytest.raises(LaunchError):
        api._trusted_publisher(winapi.TrustFile(), 1)
    assert actions == [1, 2]


def test_null_dacl_is_untrusted():
    with pytest.raises(LaunchError):
        native()._check_dacl(None)
