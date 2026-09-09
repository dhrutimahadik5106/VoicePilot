"""Replaceable capture interface and safe audio errors."""
from typing import Callable, Literal, Protocol

from app.core.errors import VoicePilotError
from app.audio.models import ErrorCode, RecordingResult, RecordingState

Control = Callable[[], Literal["stop", "cancel"] | None]


class AudioError(VoicePilotError):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code.value)


class AudioRecorder(Protocol):
    @property
    def state(self) -> RecordingState: ...

    def record(self, duration_seconds: float | None = None,
               control: Control | None = None) -> RecordingResult: ...

    def stop(self) -> None: ...

    def cancel(self) -> None: ...
