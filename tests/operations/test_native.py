import ctypes as c
from contextlib import contextmanager
import pytest
from app.operations import windows
from app.operations.models import Code, OperationError


@pytest.fixture
def endpoint(monkeypatch):
    calls=[]
    @contextmanager
    def fake_endpoint():
        yield object(),"default-test"
    monkeypatch.setattr(windows,"endpoint",fake_endpoint)
    def call(obj,slot,types,*args):
        calls.append((slot,args))
        if slot==9:c.cast(args[0],c.POINTER(c.c_float))[0]=.4
        if slot==15:c.cast(args[0],c.POINTER(windows.w.BOOL))[0]=True
        return 0
    monkeypatch.setattr(windows,"call",call)
    return calls


def test_fixed_audio_methods_preserve_mute(endpoint):
    api=windows.WindowsBackend()
    state=api.read_volume()
    assert abs(state.percent-40)<.001 and state.muted
    api.set_volume(60,"default-test",lambda:None)
    assert [item[0] for item in endpoint]==[9,15,7]
    assert endpoint[-1][1]==(.6,None)


def test_fixed_mute_method(endpoint):
    windows.WindowsBackend().set_mute(False,"default-test",lambda:None)
    assert endpoint==[(14,(False,None))]


def test_default_endpoint_change_blocks_write(endpoint):
    with pytest.raises(OperationError):windows.WindowsBackend().set_volume(60,"other",lambda:None)
    assert endpoint==[]


def test_guard_immediately_before_native_mutation(endpoint):
    def deny():raise OperationError(Code.CANCELLED)
    with pytest.raises(OperationError):windows.WindowsBackend().set_mute(True,"default-test",deny)
    assert endpoint==[]


def test_real_brightness_mutation_always_unsupported():
    with pytest.raises(OperationError) as error:windows.WindowsBackend().set_brightness(50,"internal",lambda:None)
    assert error.value.code==Code.UNSUPPORTED


def test_no_native_access_on_default_construction():
    windows.WindowsBackend()


@pytest.mark.parametrize('hr,code',[(-2147024891,Code.DENIED),(-1,Code.UNAVAILABLE)])
def test_safe_native_error_codes(hr,code):
    with pytest.raises(OperationError) as error:windows.check(hr)
    assert error.value.code==code


def test_brightness_query_is_fixed_and_read_only(monkeypatch):
    from contextlib import contextmanager
    strings=[];calls=[]
    @contextmanager
    def com():yield object()
    monkeypatch.setattr(windows,'com',com)
    monkeypatch.setattr(windows,'dll',lambda _:object())
    monkeypatch.setattr(windows,'instantiate',lambda *a:windows.P(10))
    def function(lib,name,*types):
        if name=='SysAllocString':
            return lambda value:strings.append(value) or len(strings)
        return lambda *a:0
    monkeypatch.setattr(windows,'function',function)
    def call(obj,slot,types,*args):
        calls.append(slot)
        if slot==4 and len(args)==4:
            c.cast(args[3],c.POINTER(windows.w.ULONG))[0]=0
            return 1
        return 0
    monkeypatch.setattr(windows,'call',call)
    result=windows.brightness_probe()
    assert not result.supported and not result.mutation_supported
    assert strings==['ROOT\\WMI','WQL','SELECT CurrentBrightness FROM WmiMonitorBrightness WHERE Active = TRUE']
    assert 20 in calls and set(calls)<={2,3,4,20}


@pytest.mark.parametrize("fail", [False, True])
def test_capture_uses_fixed_target_and_releases_resources(monkeypatch, fail):
    from app.operations import capture
    calls = []
    monkeypatch.setattr(capture, "dll", lambda name: name)

    def function(lib, name, *types):
        def invoke(*args):
            calls.append((name, args))
            if name == "GetDC":
                assert args == (None,)
                return 1
            if name == "GetDeviceCaps":
                return 2
            if name == "CreateCompatibleDC":
                return 2
            if name == "CreateCompatibleBitmap":
                return 3
            if name == "SelectObject":
                return 4
            if name == "BitBlt":
                assert args == (2, 0, 0, 2, 2, 1, 0, 0, 0x40CC0020)
                return not fail
            if name == "GetDIBits":
                return 2
            return 1
        return invoke

    monkeypatch.setattr(capture, "function", function)
    if fail:
        with pytest.raises(OperationError):
            capture.capture_primary(lambda: None)
    else:
        assert capture.validate_bmp(capture.capture_primary(lambda: None)) == (2, 2)
    assert [name for name, _ in calls][-3:] == ["DeleteObject", "DeleteDC", "ReleaseDC"]


def test_capture_cancelled_before_native_access():
    from app.operations.capture import capture_primary

    def cancel():
        raise OperationError(Code.CANCELLED)

    with pytest.raises(OperationError) as error:
        capture_primary(cancel)
    assert error.value.code == Code.CANCELLED
