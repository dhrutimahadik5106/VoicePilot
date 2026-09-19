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


@pytest.mark.parametrize("package,mask,accepted", [(True, 0x1200A9, True),
    (False, 0x1200A9, False), (True, 0x120116, False), (True, 0x10000000, False)])
def test_conditional_acl_only_read_access_in_notepad_package(monkeypatch, package, mask, accepted):
    api = native()
    ace = C.create_string_buffer(32)
    ace[0] = bytes([9])
    C.cast(C.addressof(ace) + 4, C.POINTER(winapi.D))[0] = mask
    def function(library, name, *signature):
        if name == "GetAclInformation":
            def info(dacl, output, size, kind):
                output[0] = 1
                return True
            return info
        assert name == "GetAce"
        def get(dacl, index, output):
            C.cast(output, C.POINTER(winapi.P))[0] = C.addressof(ace)
            return True
        return get
    monkeypatch.setattr(winapi, "function", function)
    if accepted:
        api._check_dacl(winapi.P(1), package=package)
    else:
        with pytest.raises(LaunchError):
            api._check_dacl(winapi.P(1), package=package)


def test_launcher_handle_retained_with_start_time(monkeypatch):
    from app.launch.notepad import CreatedProcess
    api = native()
    api._check_not_elevated = lambda: None
    api.process_created = lambda handle: 123456
    def create(*args):
        process = C.cast(args[9], C.POINTER(winapi.ProcessInfo)).contents
        process.pid, process.process, process.thread = 123, 11, 12
        return True
    monkeypatch.setattr(winapi, "function", lambda *args: create)
    result = api.create_process("C:/Windows/System32/notepad.exe", "C:/Windows/System32", retain=True)
    assert type(result) is CreatedProcess and result.pid == 123 and result.created == 123456
    assert result.handle == 11 and api.closed == [12]


def test_notepad_snapshot_filters_before_process_queries(monkeypatch):
    from app.launch.notepad import AUMID, FAMILY
    api = native()
    opened = []
    entries = iter([(7, "Unrelated.exe", 2), (8, "notepad.exe", 3)])
    def advance(snapshot, pointer):
        try:
            pid, name, parent = next(entries)
        except StopIteration:
            C.set_last_error(18)
            return False
        entry = pointer._obj
        entry.pid, entry.name, entry.parent = pid, name, parent
        return True
    def open_process(access, inherit, pid):
        opened.append(pid)
        assert access == 0x101000 and not inherit
        return 66
    def query(handle, flags, path, size):
        path.value = "C:/Windows/System32/notepad.exe"
        return True
    functions = {"CreateToolhelp32Snapshot": lambda *a: 1,
        "Process32FirstW": advance, "Process32NextW": advance,
        "OpenProcess": open_process, "QueryFullProcessImageNameW": query,
        "WaitForSingleObject": lambda *a: 258}
    monkeypatch.setattr(winapi, "function", lambda library, name, *a: functions[name])
    api.process_created = lambda handle: 123456
    api.package_string = lambda handle, name: ""
    records = api.notepad_processes()
    assert len(records) == 1 and records[0].pid == 8 and records[0].parent_pid == 3
    assert opened == [8] and api.closed == [66, 1]
    assert records[0].model_dump() == {}
