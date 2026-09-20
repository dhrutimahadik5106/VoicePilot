"""Lazy fixed Windows interfaces. No shell, dynamic input-driven COM or device selection."""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager
from uuid import UUID
from app.operations.models import Volume, Brightness, OperationError, Code

P = c.c_void_p


class GUID(c.Structure):
    _fields_ = [("data", c.c_byte * 16)]


def guid(value):
    return GUID.from_buffer_copy(UUID(value).bytes_le)


def dll(name):
    import sys
    if sys.platform != "win32":
        raise OperationError(Code.UNSUPPORTED)
    return c.WinDLL(name, use_last_error=True, winmode=0x800)


def function(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


def check(hr):
    if hr < 0:
        raise OperationError(Code.DENIED if hr & 0xFFFFFFFF == 0x80070005 else Code.UNAVAILABLE)


def call(obj, slot, types, *args):
    table = c.cast(obj, c.POINTER(c.POINTER(P))).contents
    fn = c.WINFUNCTYPE(c.c_long, P, *types)(table[slot])
    value = fn(obj, *args)
    check(value)
    return value


def mutation_call(obj, slot, types, *args):
    try:
        return call(obj, slot, types, *args)
    except OperationError as error:
        raise OperationError(Code.DENIED if error.code == Code.DENIED else Code.FAILED) from None


def release(obj):
    if obj:
        call(obj, 2, ())


@contextmanager
def com():
    ole = dll("ole32.dll")
    initialize = function(ole, "CoInitializeEx", c.c_long, P, w.DWORD)
    check(initialize(None, 0))
    try:
        yield ole
    finally:
        function(ole, "CoUninitialize", None)()


def instantiate(ole, class_id, interface_id):
    out = P()
    clsid, iid = guid(class_id), guid(interface_id)
    check(function(ole, "CoCreateInstance", c.c_long, c.POINTER(GUID), P, w.DWORD,
                   c.POINTER(GUID), c.POINTER(P))(c.byref(clsid), None, 1, c.byref(iid), c.byref(out)))
    return out


@contextmanager
def endpoint():
    with com() as ole:
        enumerator = device = control = None
        try:
            enumerator = instantiate(ole, "bcde0395-e52f-467c-8e3d-c4579291692e",
                                     "a95664d2-9614-4f35-a746-de8db63617e6")
            device, control = P(), P()
            call(enumerator, 4, (c.c_int, c.c_int, c.POINTER(P)), 0, 1, c.byref(device))
            iid = guid("5cdf2c82-841e-4546-9722-0cf74078229a")
            call(device, 3, (c.POINTER(GUID), w.DWORD, P, c.POINTER(P)), c.byref(iid), 1, None, c.byref(control))
            identifier = P()
            call(device, 5, (c.POINTER(P),), c.byref(identifier))
            try:
                key = c.wstring_at(identifier)
            finally:
                function(ole, "CoTaskMemFree", None, P)(identifier)
            yield control, key
        finally:
            release(control)
            release(device)
            release(enumerator)


class WindowsBackend:
    fake = False

    def read_volume(self):
        with endpoint() as (control, key):
            level, muted = c.c_float(), w.BOOL()
            call(control, 9, (c.POINTER(c.c_float),), c.byref(level))
            call(control, 15, (c.POINTER(w.BOOL),), c.byref(muted))
            return Volume(percent=float(level.value) * 100, muted=bool(muted.value), endpoint=key)

    def set_volume(self, percent, expected_endpoint, guard):
        if type(percent) not in (int, float) or not 0 <= percent <= 100:
            raise OperationError(Code.INVALID)
        with endpoint() as (control, key):
            if key != expected_endpoint:
                raise OperationError(Code.NO_OBSERVATION)
            guard()
            mutation_call(control, 7, (c.c_float, P), percent / 100, None)
            # Do not alter mute state. Independent read verifies it stayed unchanged.

    def set_mute(self, muted, expected_endpoint, guard):
        if type(muted) is not bool:
            raise OperationError(Code.INVALID)
        with endpoint() as (control, key):
            if key != expected_endpoint:
                raise OperationError(Code.NO_OBSERVATION)
            guard()
            mutation_call(control, 14, (w.BOOL, P), muted, None)

    def read_brightness(self):
        return brightness_probe()

    def set_brightness(self, percent, target, guard):
        raise OperationError(Code.UNSUPPORTED)

    def capture(self, guard):
        from app.operations.capture import capture_primary
        return capture_primary(guard)


class VariantValue(c.Union):
    _fields_ = [("integer", c.c_long), ("byte", c.c_ubyte), ("short", c.c_short),
                ("storage", P * 2)]


class Variant(c.Structure):
    _fields_ = [("kind", w.WORD), ("r1", w.WORD), ("r2", w.WORD), ("r3", w.WORD),
                ("value", VariantValue)]


def brightness_probe():
    """Exactly one active WmiMonitorBrightness interface; no instance names retained."""
    with com() as ole:
        automation = dll("oleaut32.dll")
        allocate = function(automation, "SysAllocString", P, w.LPCWSTR)
        free = function(automation, "SysFreeString", None, P)
        strings = [allocate(text) for text in ("ROOT\\WMI", "WQL",
                   "SELECT CurrentBrightness FROM WmiMonitorBrightness WHERE Active = TRUE")]
        locator = services = enumerator = None
        objects = (P * 2)()
        try:
            if not all(strings):
                raise OperationError(Code.UNAVAILABLE)
            locator = instantiate(ole, "4590f811-1d3a-11d0-891f-00aa004b2e24",
                                  "dc12a687-737f-11cf-884d-00aa004b2e24")
            services, enumerator = P(), P()
            call(locator, 3, (P, P, P, P, c.c_long, P, P, c.POINTER(P)),
                 strings[0], None, None, None, 0x80, None, None, c.byref(services))
            check(function(ole, "CoSetProxyBlanket", c.c_long, P, w.DWORD, w.DWORD, P,
                           w.DWORD, w.DWORD, P, w.DWORD)(services, 10, 0, None, 3, 3, None, 0))
            call(services, 20, (P, P, c.c_long, P, c.POINTER(P)),
                 strings[1], strings[2], 0x30, None, c.byref(enumerator))
            count = w.ULONG()
            hr = call(enumerator, 4, (c.c_long, w.ULONG, c.POINTER(P), c.POINTER(w.ULONG)),
                      1000, 2, objects, c.byref(count))
            if count.value == 0 and hr == 1:
                return Brightness(supported=False)
            if count.value != 1 or hr != 1:
                return Brightness(supported=False)  # Multiple/uncertain display targets are unsupported.
            value = Variant()
            try:
                call(objects[0], 4, (w.LPCWSTR, c.c_long, c.POINTER(Variant), P, P),
                     "CurrentBrightness", 0, c.byref(value), None, None)
                if value.kind not in (3, 17):
                    raise OperationError(Code.NO_OBSERVATION)
                percent = value.value.byte if value.kind == 17 else value.value.integer
                return Brightness(supported=True, percent=percent, mutation_supported=False)
            finally:
                function(automation, "VariantClear", c.c_long, c.POINTER(Variant))(c.byref(value))
        except OperationError as error:
            if error.code == Code.DENIED:
                raise
            return Brightness(supported=False)
        finally:
            for obj in objects:
                release(obj)
            release(enumerator)
            release(services)
            release(locator)
            for value in strings:
                if value:
                    free(value)
