"""Versioned, exact English basic-operation aliases; no fuzzy matching or execution."""
import re
from types import MappingProxyType
from app.operations.models import Capability as C, Plan, OperationError, Code

VERSION = "6b-v1"
ALIASES = MappingProxyType({
    "increase volume": C.VOLUME_UP, "decrease volume": C.VOLUME_DOWN,
    "mute": C.MUTE, "unmute": C.UNMUTE,
    "read volume": C.VOLUME_READ, "read mute state": C.MUTE_READ,
    "increase brightness": C.BRIGHTNESS_UP, "decrease brightness": C.BRIGHTNESS_DOWN,
    "read brightness": C.BRIGHTNESS_READ, "take a screenshot": C.SCREENSHOT,
    "stop": C.STOP, "cancel": C.CANCEL, "what did you do?": C.HISTORY,
})


def resolve_basic(text):
    if type(text) is not str or not 0 < len(text) <= 120:
        raise OperationError(Code.INVALID)
    normalized = text.strip().casefold()
    if normalized in ALIASES:
        return Plan(capability=ALIASES[normalized])
    match = re.fullmatch(r"set (volume|brightness) to (0|[1-9][0-9]?|100) percent", normalized)
    if match:
        return Plan(capability=C.VOLUME_SET if match[1] == "volume" else C.BRIGHTNESS_SET,
                    percentage=int(match[2]))
    raise OperationError(Code.INVALID)
