"""Lazy standard-library Win32 boundary; never loaded during normal imports."""
import os
from app.speaker.contracts import SpeakerError

ENTROPY = b"VoicePilot/speaker-profile/v1"
LIMIT = 131072
SDDL = "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)"

class WindowsAPI:
    def __init__(self):
        if os.name != "nt":
            raise SpeakerError("protection_unavailable")
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.crypt = c.WinDLL("crypt32.dll", use_last_error=True, winmode=0x800)
        self.kernel = c.WinDLL("kernel32.dll", use_last_error=True, winmode=0x800)
        self.advapi = c.WinDLL("advapi32.dll", use_last_error=True, winmode=0x800)
        class Blob(c.Structure):
            _fields_ = [("size", w.DWORD), ("data", c.POINTER(c.c_ubyte))]
        self.Blob = Blob
        self.crypt.CryptProtectData.argtypes = [c.POINTER(Blob), w.LPCWSTR, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
        self.crypt.CryptProtectData.restype = w.BOOL
        self.crypt.CryptUnprotectData.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
        self.crypt.CryptUnprotectData.restype = w.BOOL
        self.kernel.LocalFree.argtypes = [c.c_void_p]
        self.kernel.LocalFree.restype = c.c_void_p
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
        self.advapi.SetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,c.c_void_p]
        self.advapi.SetFileSecurityW.restype = w.BOOL

    def crypt_bytes(self, data, decrypt=False):
        c, Blob = self.c, self.Blob
        raw = (c.c_ubyte * len(data)).from_buffer_copy(data)
        entropy = (c.c_ubyte * len(ENTROPY)).from_buffer_copy(ENTROPY)
        source, extra, output = Blob(len(data),raw), Blob(len(ENTROPY),entropy), Blob()
        try:
            fn = self.crypt.CryptUnprotectData if decrypt else self.crypt.CryptProtectData
            # UI_FORBIDDEN only; never LOCAL_MACHINE.
            if not fn(c.byref(source),None,c.byref(extra),None,None,1,c.byref(output)):
                raise SpeakerError("protection_failed")
            if not output.data or not 0 < output.size <= LIMIT:
                raise SpeakerError("protection_failed")
            return c.string_at(output.data, output.size)
        finally:
            c.memset(raw,0,len(data))
            if output.data:
                c.memset(output.data,0,output.size)
                self.kernel.LocalFree(output.data)

    def restrict_directory(self, path):
        c, w = self.c, self.w
        descriptor = c.c_void_p()
        try:
            if not self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(SDDL,1,c.byref(descriptor),None):
                raise SpeakerError("protection_failed")
            # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
            if not self.advapi.SetFileSecurityW(str(path),0x80000004,descriptor):
                raise SpeakerError("protection_failed")
        finally:
            if descriptor:
                self.kernel.LocalFree(descriptor)
