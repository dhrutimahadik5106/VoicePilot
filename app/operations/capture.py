"""One consent-triggered primary-display GDI capture; never inspect image content."""
import ctypes as c
from ctypes import wintypes as w
import struct
from app.operations.windows import dll, function, P
from app.operations.models import OperationError, Code

MAX_BYTES = 64 * 1024 * 1024


def encode_header(width, height):
    size = width * height * 4
    return (struct.pack("<2sIHHI", b"BM", 54 + size, 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, size, 0, 0, 0, 0))


def validate_bmp(data):
    # Structural validation only: do not decode, recognize, display or inspect pixels.
    if type(data) is not bytes or not 54 < len(data) <= MAX_BYTES:
        raise OperationError(Code.UNVERIFIED)
    try:
        magic, size, reserved1, reserved2, offset = struct.unpack("<2sIHHI", data[:14])
        header, width, height, planes, depth, compression, pixels, x, y, colors, important = struct.unpack("<IiiHHIIiiII", data[14:54])
        if (magic != b"BM" or size != len(data) or reserved1 or reserved2 or offset != 54 or header != 40
                or not 0 < width <= 16384 or not 0 < height <= 16384 or planes != 1
                or depth != 32 or compression != 0 or pixels != width * height * 4
                or len(data) != 54 + pixels or colors or important):
            raise ValueError()
        return width, height
    except Exception:
        raise OperationError(Code.UNVERIFIED) from None


def capture_primary(guard):
    guard()
    user, gdi = dll("user32.dll"), dll("gdi32.dll")
    screen = memory = bitmap = old = None
    try:
        screen = function(user, "GetDC", P, P)(None)
        if not screen:
            raise OperationError(Code.UNAVAILABLE)
        caps = function(gdi, "GetDeviceCaps", c.c_int, P, c.c_int)
        width, height = caps(screen, 8), caps(screen, 10)
        if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height * 4 + 54 > MAX_BYTES:
            raise OperationError(Code.UNSUPPORTED)
        memory = function(gdi, "CreateCompatibleDC", P, P)(screen)
        bitmap = function(gdi, "CreateCompatibleBitmap", P, P, c.c_int, c.c_int)(screen, width, height)
        if not memory or not bitmap:
            raise OperationError(Code.FAILED)
        select = function(gdi, "SelectObject", P, P, P)
        old = select(memory, bitmap)
        if not old or old == c.c_void_p(-1).value:
            raise OperationError(Code.FAILED)
        guard()
        if not function(gdi, "BitBlt", w.BOOL, P, c.c_int, c.c_int, c.c_int, c.c_int,
                        P, c.c_int, c.c_int, w.DWORD)(memory, 0, 0, width, height, screen, 0, 0, 0x40CC0020):
            raise OperationError(Code.FAILED)
        select(memory, old)
        old = None
        header = encode_header(width, height)
        info = c.create_string_buffer(header[14:])
        pixels = c.create_string_buffer(width * height * 4)
        rows = function(gdi, "GetDIBits", c.c_int, P, P, w.UINT, w.UINT, P, P, w.UINT)(
            screen, bitmap, 0, height, pixels, info, 0)
        if rows != height:
            raise OperationError(Code.FAILED)
        guard()
        return header + pixels.raw
    finally:
        if old and memory:
            function(gdi, "SelectObject", P, P, P)(memory, old)
        if bitmap:
            function(gdi, "DeleteObject", w.BOOL, P)(bitmap)
        if memory:
            function(gdi, "DeleteDC", w.BOOL, P)(memory)
        if screen:
            function(user, "ReleaseDC", c.c_int, P, P)(None, screen)
