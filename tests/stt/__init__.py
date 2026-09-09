"""STT test helpers; real model, microphone and network access are forbidden."""
import importlib.abc
import socket
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.audio.models import AudioFormat, RecordedAudio


@pytest.fixture(autouse=True)
def isolated_stt(monkeypatch, tmp_path):
    import os
    for key in list(os.environ):
        if key.startswith("VOICEPILOT_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    class BlockHardwareAndModels(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"faster_whisper", "sounddevice", "ctranslate2"}:
                raise AssertionError("Real model/hardware imports forbidden in STT tests")
    monkeypatch.setattr(sys, "meta_path", [BlockHardwareAndModels(), *sys.meta_path])
    def no_network(*args, **kwargs):
        raise AssertionError("Network forbidden in STT tests")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)


def audio(seconds=1, rate=16000, channels=1):
    return RecordedAudio(format=AudioFormat(sample_rate=rate, channels=channels),
                         samples=np.ones((int(rate * seconds), channels), dtype=np.int16))


def segment(text=" hello", start=0.0, end=.5, words=None):
    return SimpleNamespace(text=text, start=start, end=end, words=words)


class FakeModel:
    supported_languages = ["en", "hi", "mr"]

    def __init__(self, segments=None, language="en"):
        self.segments = segments if segments is not None else [segment()]
        self.language = language
        self.calls = []
        self.closed = False

    def transcribe(self, samples, **kwargs):
        self.calls.append((samples, kwargs))
        def generate():
            try:
                yield from self.segments
            finally:
                self.closed = True
        return generate(), SimpleNamespace(language=self.language, language_probability=.87)


class FakeEngine:
    def __init__(self):
        self.requests = []

    def transcribe(self, request, cancel=None):
        from app.stt.models import TranscriptSegment, TranscriptionResult, TranscriptionStatus
        self.requests.append(request)
        return TranscriptionResult(
            audio_id=request.audio_id, execution_correlation_id=request.execution_correlation_id,
            text="hello", language=request.language or "en", language_probability=None,
            segments=(TranscriptSegment(text="hello", start=0, end=min(.5, request.audio.duration)),),
            processing_duration=.25, source_audio_duration=request.audio.duration,
            model_name="base", device="cpu", compute_type="int8",
            status=TranscriptionStatus.SUCCEEDED,
        )
