"""Device queries are explicit and do not open capture streams."""
import importlib

from app.audio.contracts import AudioError
from app.audio.models import ErrorCode, InputDevice


def load_backend():
    # Importing sounddevice initializes PortAudio; defer even that to explicit use.
    return importlib.import_module("sounddevice")


def error_code(error: Exception) -> ErrorCode:
    if isinstance(error, AudioError):
        return error.code
    if isinstance(error, PermissionError):
        return ErrorCode.PERMISSION_DENIED
    # PortAudio's stable numeric error codes; never inspect or expose error text.
    if len(error.args) > 1 and error.args[1] == -9996:
        return ErrorCode.DEVICE_NOT_FOUND
    if len(error.args) > 1 and error.args[1] == -9985:
        return ErrorCode.DEVICE_UNAVAILABLE
    return ErrorCode.STREAM_FAILED


def list_input_devices(backend=None) -> list[InputDevice]:
    try:
        backend = backend if backend is not None else load_backend()
        devices = [
            InputDevice(index=index, name=info["name"],
                        max_input_channels=info["max_input_channels"],
                        default_sample_rate=info["default_samplerate"])
            for index, info in enumerate(backend.query_devices())
            if info["max_input_channels"] > 0
        ]
        if not devices:
            raise AudioError(ErrorCode.DEVICE_NOT_FOUND)
        return devices
    except Exception as error:
        raise AudioError(error_code(error)) from None


def select_input_device(identifier: int | str | None, backend=None) -> InputDevice:
    backend = backend if backend is not None else load_backend()
    devices = list_input_devices(backend)
    if identifier is None:
        try:
            identifier = int(backend.default.device[0])
        except Exception:
            raise AudioError(ErrorCode.DEVICE_NOT_FOUND) from None
    if isinstance(identifier, int):
        matches = [device for device in devices if device.index == identifier]
    else:
        matches = [device for device in devices if device.name.casefold() == identifier.casefold()]
    if len(matches) != 1:
        raise AudioError(ErrorCode.DEVICE_NOT_FOUND)
    return matches[0]
