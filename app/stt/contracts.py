"""Replaceable STT interface and controlled exceptions."""
from threading import Event
from typing import Protocol

from app.core.errors import VoicePilotError
from app.stt.models import TranscriptionErrorCode, TranscriptionRequest, TranscriptionResult


class TranscriptionError(VoicePilotError):
    def __init__(self, code: TranscriptionErrorCode):
        self.code = code
        super().__init__(code.value)


class SpeechToTextEngine(Protocol):
    def transcribe(self, request: TranscriptionRequest,
                   cancel: Event | None = None) -> TranscriptionResult: ...
