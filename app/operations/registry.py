"""Immutable capability and risk metadata; never dynamic dispatch from text."""
from types import MappingProxyType
from dataclasses import dataclass
from app.operations.models import Capability as C


@dataclass(frozen=True)
class Spec:
    risk: str
    mutation: bool
    idempotent: bool
    rollback_supported: bool = False
    cancellation_supported: bool = True
    max_retries: int = 0


READS = frozenset({C.VOLUME_READ, C.MUTE_READ, C.BRIGHTNESS_READ, C.HISTORY})
SAFETY = frozenset({C.CANCEL, C.STOP})
REGISTRY = MappingProxyType({cap: Spec(
    "safety" if cap in SAFETY else "informational" if cap in READS else
    "privacy_sensitive" if cap in {C.SCREENSHOT, C.SCREENSHOT_DELETE} else "low",
    cap not in READS | SAFETY,
    cap not in {C.VOLUME_UP, C.VOLUME_DOWN, C.BRIGHTNESS_UP, C.BRIGHTNESS_DOWN, C.SCREENSHOT})
    for cap in C})
