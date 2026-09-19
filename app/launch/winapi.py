"""Narrow lazy Windows API wrapper. No discovery or process creation on import."""
import ctypes as C
from ctypes import wintypes as W
from uuid import UUID
from app.launch.models import LaunchError, Status

P = C.c_void_p
D = W.DWORD
H = W.HANDLE


class GUID(C.Structure):
    _fields_ = [("data", C.c_byte * 16)]


class TrustFile(C.Structure):
    _fields_ = [("size", D), ("path", W.LPCWSTR), ("handle", H), ("subject", P)]


class TrustData(C.Structure):
    _fields_ = [("size", D), ("callback", P), ("sip", P), ("ui", D), ("revocation", D),
                ("choice", D), ("info", P), ("action", D), ("state", H), ("url", W.LPCWSTR),
                ("flags", D), ("context", D), ("settings", P)]


class CatalogInfo(C.Structure):
    _fields_ = [("size", D), ("path", W.WCHAR * 260)]


class TrustCatalog(C.Structure):
    _fields_ = [("size", D), ("version", D), ("catalog_path", W.LPCWSTR),
                ("member_tag", W.LPCWSTR), ("member_path", W.LPCWSTR), ("member", H),
                ("hash", P), ("hash_size", D), ("context", P), ("admin", H)]


class CertPrefix(C.Structure):
    _fields_ = [("size", D), ("cert", P)]


class Mapping(C.Structure):
    _fields_ = [("read", D), ("write", D), ("execute", D), ("all", D)]


class FileInfo(C.Structure):
    _fields_ = [("attributes", D), ("created", W.FILETIME), ("accessed", W.FILETIME),
                ("written", W.FILETIME), ("volume", D), ("size_high", D), ("size_low", D),
                ("links", D), ("index_high", D), ("index_low", D)]


class Startup(C.Structure):
    _fields_ = [("size", D), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR), ("title", W.LPWSTR),
                ("x", D), ("y", D), ("width", D), ("height", D), ("chars_x", D), ("chars_y", D),
                ("fill", D), ("flags", D), ("show", W.WORD), ("reserved_size", W.WORD),
                ("reserved_data", P), ("stdin", H), ("stdout", H), ("stderr", H)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", H), ("thread", H), ("pid", D), ("tid", D)]


def function(library, name, result, *arguments):
    fn = getattr(library, name)
    fn.restype = result
    fn.argtypes = list(arguments)
    return fn


class Native:
    def __init__(self):
        import sys
        if sys.platform != "win32":
            raise LaunchError(Status.DISABLED)
        def library(name):
            return C.WinDLL(name, use_last_error=True, winmode=0x800)
        self.kernel = library("kernel32.dll")
        self.security = library("advapi32.dll")
        self.shell = library("shell32.dll")
        self.ole = library("ole32.dll")
        self.trust = library("wintrust.dll")
        self.crypto = library("crypt32.dll")
        self.version = library("version.dll")
        self.psapi = library("psapi.dll")
        self.close = function(self.kernel, "CloseHandle", W.BOOL, H)
        self._check_not_elevated()

    def _token(self):
        token = H()
        current = function(self.kernel, "GetCurrentProcess", H)()
        if not function(self.security, "OpenProcessToken", W.BOOL, H, D, C.POINTER(H))(current, 0xA, C.byref(token)):
            raise LaunchError(Status.ACCESS_DENIED)
        return token

    def _check_not_elevated(self):
        token = self._token()
        try:
            elevated, size = D(), D()
            fn = function(self.security, "GetTokenInformation", W.BOOL, H, C.c_int, P, D, C.POINTER(D))
            if not fn(token, 20, C.byref(elevated), C.sizeof(elevated), C.byref(size)) or elevated.value:
                raise LaunchError(Status.ACCESS_DENIED)
        finally:
            self.close(token)

    def roots(self):
        buffer = C.create_unicode_buffer(32768)
        size = function(self.kernel, "GetSystemDirectoryW", W.UINT, W.LPWSTR, W.UINT)(buffer, len(buffer))
        if not 0 < size < len(buffer):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        system = buffer.value
        folders = []
        for value in ("905e63b6-c1bf-494e-b29c-65b732d3d21a", "7c5a40ef-a0fb-4bfc-874a-c0f2e0b9fa8e"):
            guid = GUID.from_buffer_copy(UUID(value).bytes_le)
            output = P()
            fn = function(self.shell, "SHGetKnownFolderPath", C.c_long, C.POINTER(GUID), D, H, C.POINTER(P))
            if fn(C.byref(guid), 0, None, C.byref(output)) == 0:
                try:
                    folders.append(C.wstring_at(output))
                finally:
                    function(self.ole, "CoTaskMemFree", None, P)(output)
        if not folders:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        return system, tuple(dict.fromkeys(folders))

    def attributes(self, path):
        value = function(self.kernel, "GetFileAttributesW", D, W.LPCWSTR)(str(path))
        if value == 0xFFFFFFFF:
            raise LaunchError(Status.NOT_INSTALLED)
        return value

    def lock(self, path, directory=False):
        flags = 0x02000000 if directory else 0
        access = 0x20080 if directory else 0x80020000
        fn = function(self.kernel, "CreateFileW", H, W.LPCWSTR, D, D, P, D, D, H)
        handle = fn(str(path), access, 1, None, 3, flags, None)
        if handle in (None, C.c_void_p(-1).value):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        return handle

    def final_path(self, handle):
        buffer = C.create_unicode_buffer(32768)
        fn = function(self.kernel, "GetFinalPathNameByHandleW", D, H, W.LPWSTR, D, D)
        count = fn(handle, buffer, len(buffer), 0)
        if not 0 < count < len(buffer):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        value = buffer.value
        # Kernel canonical drive paths have a fixed four-character device prefix.
        return value[4:] if value.startswith(chr(92) * 2 + "?" + chr(92)) else value

    def protected(self, handle, *, package=False):
        descriptor, dacl = P(), P()
        get = function(self.security, "GetSecurityInfo", D, H, C.c_int, D, P, P, P, P, C.POINTER(P))
        if get(handle, 1, 7, None, None, C.byref(dacl), None, C.byref(descriptor)):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        token = duplicate = None
        try:
            self._check_dacl(dacl, package=package)
            token = self._token()
            duplicate = H()
            if not function(self.security, "DuplicateToken", W.BOOL, H, C.c_int, C.POINTER(H))(token, 2, C.byref(duplicate)):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            mapping = Mapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
            privileges = C.create_string_buffer(2048)
            length, granted, allowed = D(len(privileges)), D(), W.BOOL()
            check = function(self.security, "AccessCheck", W.BOOL, P, H, D, C.POINTER(Mapping), P,
                             C.POINTER(D), C.POINTER(D), C.POINTER(W.BOOL))
            if not check(descriptor, duplicate, 0x02000000, C.byref(mapping), privileges,
                         C.byref(length), C.byref(granted), C.byref(allowed)) or not allowed.value:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            # Write/append, delete-child, write attributes/EA, delete, change ACL/owner.
            if granted.value & 0xD0156:
                raise LaunchError(Status.IDENTITY_MISMATCH)
        finally:
            if duplicate:
                self.close(duplicate)
            if token:
                self.close(token)
            function(self.kernel, "LocalFree", H, H)(descriptor)

    def _check_dacl(self, dacl, *, package=False):
        if not dacl:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        info = (D * 3)()
        if not function(self.security, "GetAclInformation", W.BOOL, P, P, D, C.c_int)(dacl, info, C.sizeof(info), 2):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        if info[0] > 256:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        trusted = {"S-1-5-18", "S-1-5-32-544",
                   "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"}
        for index in range(info[0]):
            ace = P()
            if not function(self.security, "GetAce", W.BOOL, P, D, C.POINTER(P))(dacl, index, C.byref(ace)):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            header = C.cast(ace, C.POINTER(C.c_ubyte))
            if header[0] == 1 or header[1] & 8:
                continue
            mask = C.cast(ace.value + 4, C.POINTER(D))[0]
            # Notepad packages contain conditional READ/EXECUTE ACEs. These cannot
            # grant any write authority; conditional write ACEs still fail closed.
            if package and header[0] == 9 and not mask & (0xD0156 | 0x50000000):
                continue
            if header[0] != 0:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            if not mask & (0xD0156 | 0x50000000):
                continue
            sid = P()
            if not function(self.security, "ConvertSidToStringSidW", W.BOOL, P, C.POINTER(P))(ace.value + 8, C.byref(sid)):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            try:
                if C.wstring_at(sid) not in trusted:
                    raise LaunchError(Status.IDENTITY_MISMATCH)
            finally:
                function(self.kernel, "LocalFree", H, H)(sid)

    def file_identity(self, handle):
        info = FileInfo()
        if not function(self.kernel, "GetFileInformationByHandle", W.BOOL, H, C.POINTER(FileInfo))(handle, C.byref(info)):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        return (info.volume, info.index_high, info.index_low, info.size_high, info.size_low,
                info.written.dwHighDateTime, info.written.dwLowDateTime)

    def publisher(self, path, handle):
        info = TrustFile(C.sizeof(TrustFile), str(path), handle, None)
        try:
            return self._trusted_publisher(info, 1)
        except LaunchError:
            return self._catalog_publisher(path, handle)

    def _catalog_publisher(self, path, handle):
        from pathlib import PureWindowsPath
        admin = H()
        catalog = None
        acquire = function(self.trust, "CryptCATAdminAcquireContext2", W.BOOL, C.POINTER(H), P, W.LPCWSTR, P, D)
        if not acquire(C.byref(admin), None, "SHA256", None, 0):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        try:
            size = D()
            calculate = function(self.trust, "CryptCATAdminCalcHashFromFileHandle2", W.BOOL, H, H, C.POINTER(D), P, D)
            calculate(admin, handle, C.byref(size), None, 0)
            if size.value != 32:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            calculated = (C.c_ubyte * size.value)()
            if not calculate(admin, handle, C.byref(size), calculated, 0):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            catalog = function(self.trust, "CryptCATAdminEnumCatalogFromHash", H, H, P, D, D, P)(admin, calculated, size, 0, None)
            if not catalog:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            catalog_info = CatalogInfo()
            catalog_info.size = C.sizeof(catalog_info)
            if not function(self.trust, "CryptCATCatalogInfoFromContext", W.BOOL, H, C.POINTER(CatalogInfo), D)(catalog, C.byref(catalog_info), 0):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            system, _ = self.roots()
            catalog_path = PureWindowsPath(catalog_info.path)
            if not catalog_path.is_relative_to(PureWindowsPath(system) / "CatRoot") or catalog_path.suffix.casefold() != ".cat":
                raise LaunchError(Status.IDENTITY_MISMATCH)
            info = TrustCatalog(C.sizeof(TrustCatalog), 0, catalog_info.path,
                                bytes(calculated).hex().upper(), str(path), handle,
                                C.cast(calculated, P), size.value, None, admin)
            return self._trusted_publisher(info, 2)
        finally:
            if catalog:
                function(self.trust, "CryptCATAdminReleaseCatalogContext", W.BOOL, H, H, D)(admin, catalog, 0)
            function(self.trust, "CryptCATAdminReleaseContext", W.BOOL, H, D)(admin, 0)

    def _trusted_publisher(self, info, choice):
        guid = GUID.from_buffer_copy(UUID("00aac56b-cd44-11d0-8cc2-00c04fc295ee").bytes_le)
        data = TrustData()
        data.size, data.ui, data.choice, data.action = C.sizeof(data), 2, choice, 1
        data.info = C.cast(C.pointer(info), P)
        data.flags = 0x1000 | 0x10 | 0x2000  # Offline local trust; no network retrieval.
        verify = function(self.trust, "WinVerifyTrust", C.c_long, H, C.POINTER(GUID), P)
        try:
            if verify(C.c_void_p(-1), C.byref(guid), C.byref(data)) != 0:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            provider = function(self.trust, "WTHelperProvDataFromStateData", P, H)(data.state)
            if not provider:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            signer = function(self.trust, "WTHelperGetProvSignerFromChain", P, P, D, W.BOOL, D)(provider, 0, False, 0)
            if not signer:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            cert = function(self.trust, "WTHelperGetProvCertFromChain", C.POINTER(CertPrefix), P, D)(signer, 0)
            if not provider or not signer or not cert or not cert.contents.cert:
                raise LaunchError(Status.IDENTITY_MISMATCH)
            buffer = C.create_unicode_buffer(256)
            name = function(self.crypto, "CertGetNameStringW", D, P, D, D, P, W.LPWSTR, D)
            count = name(cert.contents.cert, 3, 0, C.cast(C.c_char_p(b"2.5.4.10"), P), buffer, len(buffer))
            if not 1 < count < len(buffer):
                raise LaunchError(Status.IDENTITY_MISMATCH)
            return buffer.value
        finally:
            data.action = 2
            verify(C.c_void_p(-1), C.byref(guid), C.byref(data))

    def original_name(self, path):
        unused = D()
        size = function(self.version, "GetFileVersionInfoSizeW", D, W.LPCWSTR, C.POINTER(D))(str(path), C.byref(unused))
        if not 0 < size < 1048576:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        buffer = C.create_string_buffer(size)
        if not function(self.version, "GetFileVersionInfoW", W.BOOL, W.LPCWSTR, D, D, P)(str(path), 0, size, buffer):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        query = function(self.version, "VerQueryValueW", W.BOOL, P, W.LPCWSTR, C.POINTER(P), C.POINTER(W.UINT))
        pointer, length = P(), W.UINT()
        slash = chr(92)
        if not query(buffer, slash + "VarFileInfo" + slash + "Translation", C.byref(pointer), C.byref(length)) or length.value < 4:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        translation = C.cast(pointer, C.POINTER(W.WORD))
        key = slash + "StringFileInfo" + slash + f"{translation[0]:04x}{translation[1]:04x}" + slash + "OriginalFilename"
        if not query(buffer, key, C.byref(pointer), C.byref(length)) or not 0 < length.value < 256:
            raise LaunchError(Status.IDENTITY_MISMATCH)
        return C.wstring_at(pointer, length.value).rstrip(chr(0))

    def create_process(self, path, directory, *, retain=False):
        self._check_not_elevated()
        startup, process = Startup(), ProcessInfo()
        startup.size = C.sizeof(startup)
        create = function(self.kernel, "CreateProcessW", W.BOOL, W.LPCWSTR, W.LPWSTR, P, P,
                          W.BOOL, D, P, W.LPCWSTR, C.POINTER(Startup), C.POINTER(ProcessInfo))
        # Fixed validated executable; NULL command line means no program arguments.
        if not create(str(path), None, None, None, False, 0, None, str(directory),
                      C.byref(startup), C.byref(process)):
            raise LaunchError(Status.LAUNCH_FAILED)
        retained = False
        try:
            if retain:
                from app.launch.notepad import CreatedProcess
                result = CreatedProcess(process.pid, self.process_created(process.process), process.process)
                retained = True
                return result
            return process.pid
        finally:
            self.close(process.thread)
            if not retained:
                self.close(process.process)

    def process_paths(self):
        pids = (D * 4096)()
        needed = D()
        if not function(self.psapi, "EnumProcesses", W.BOOL, P, D, C.POINTER(D))(pids, C.sizeof(pids), C.byref(needed)) or needed.value >= C.sizeof(pids):
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        result = []
        for pid in pids[:needed.value // C.sizeof(D)]:
            handle = function(self.kernel, "OpenProcess", H, D, W.BOOL, D)(0x1000, False, pid)
            if not handle:
                continue
            try:
                buffer, size = C.create_unicode_buffer(32768), D(32768)
                if function(self.kernel, "QueryFullProcessImageNameW", W.BOOL, H, D, W.LPWSTR, C.POINTER(D))(handle, 0, buffer, C.byref(size)):
                    result.append((pid, buffer.value))
            finally:
                self.close(handle)
        return tuple(result)


    def process_created(self, handle):
        times = [W.FILETIME() for _ in range(4)]
        fn = function(self.kernel, "GetProcessTimes", W.BOOL, H,
                      *([C.POINTER(W.FILETIME)] * 4))
        if not fn(handle, *(C.byref(t) for t in times)):
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def package_string(self, handle, name):
        size = D(256)
        buffer = C.create_unicode_buffer(size.value)
        result = function(self.kernel, name, C.c_long, H, C.POINTER(D), W.LPWSTR)(
            handle, C.byref(size), buffer)
        if result in (15700, 15703):  # No package / no application identity.
            return ""
        if result or not 0 < size.value <= len(buffer):
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        return buffer.value

    def package_path(self, full_name):
        size = D(32768)
        buffer = C.create_unicode_buffer(size.value)
        fn = function(self.kernel, "GetPackagePathByFullName", C.c_long,
                      W.LPCWSTR, C.POINTER(D), W.LPWSTR)
        if fn(full_name, C.byref(size), buffer) or not 0 < size.value <= len(buffer):
            raise LaunchError(Status.IDENTITY_MISMATCH)
        return buffer.value

    def notepad_processes(self):
        """Query only exact Notepad entries; never collect titles or command lines."""
        from app.launch.notepad import NotepadProcess
        class ProcessEntry(C.Structure):
            _fields_ = [("size", D), ("usage", D), ("pid", D), ("heap", C.c_size_t),
                        ("module", D), ("threads", D), ("parent", D),
                        ("priority", W.LONG), ("flags", D), ("name", W.WCHAR * 260)]
        snapshot = function(self.kernel, "CreateToolhelp32Snapshot", H, D, D)(2, 0)
        if snapshot in (None, C.c_void_p(-1).value):
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        records = []
        try:
            entry = ProcessEntry()
            entry.size = C.sizeof(entry)
            first = function(self.kernel, "Process32FirstW", W.BOOL, H, C.POINTER(ProcessEntry))
            following = function(self.kernel, "Process32NextW", W.BOOL, H, C.POINTER(ProcessEntry))
            more = first(snapshot, C.byref(entry))
            for _ in range(4096):
                if not more:
                    if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                    return tuple(records)
                if entry.name.casefold() == "notepad.exe":
                    if len(records) >= 32:
                        raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                    handle = function(self.kernel, "OpenProcess", H, D, W.BOOL, D)(0x101000, False, entry.pid)
                    if not handle:
                        # A disappearing snapshot entry can be retried; access denial is not absence.
                        if C.get_last_error() != 87:
                            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                    else:
                        try:
                            size = D(32768)
                            path = C.create_unicode_buffer(size.value)
                            query = function(self.kernel, "QueryFullProcessImageNameW", W.BOOL,
                                             H, D, W.LPWSTR, C.POINTER(D))
                            if not query(handle, 0, path, C.byref(size)):
                                raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                            created = self.process_created(handle)
                            record = NotepadProcess(pid=entry.pid, parent_pid=entry.parent,
                                created=created, path=path.value,
                                family=self.package_string(handle, "GetPackageFamilyName"),
                                package=self.package_string(handle, "GetPackageFullName"),
                                aumid=self.package_string(handle, "GetApplicationUserModelId"))
                            # A handle, start time and liveness check prevent accepting an exited/reused PID.
                            wait = function(self.kernel, "WaitForSingleObject", D, H, D)(handle, 0)
                            if wait == 258:
                                records.append(record)
                            elif wait != 0:
                                raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
                        finally:
                            self.close(handle)
                more = following(snapshot, C.byref(entry))
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        finally:
            self.close(snapshot)


    def notepad_package_registered(self):
        from app.launch.notepad import FAMILY, PACKAGE_PATTERN
        import re
        count, size = D(), D()
        query = function(self.kernel, "GetPackagesByPackageFamily", C.c_long,
                         W.LPCWSTR, C.POINTER(D), P, C.POINTER(D), P)
        result = query(FAMILY, C.byref(count), None, C.byref(size), None)
        if result not in (0, 122) or count.value > 32 or size.value > 32768:
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        if count.value == 0:
            return False
        names = (W.LPWSTR * count.value)()
        buffer = C.create_unicode_buffer(size.value)
        if query(FAMILY, C.byref(count), names, C.byref(size), buffer):
            raise LaunchError(Status.OBSERVATION_UNAVAILABLE)
        return any(re.fullmatch(PACKAGE_PATTERN, name) is not None for name in names if name)
