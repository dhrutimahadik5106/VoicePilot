import importlib
import logging
import sys
from threading import Event
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from app.core.config import Settings
from app.stt.faster_whisper_engine import FasterWhisperEngine, load_model
from app.stt.models import TranscriptionErrorCode as Code, TranscriptionRequest
from tests.stt import FakeModel, audio, isolated_stt, segment


def test_lazy_load_cache_latency_order_and_options():
    model = FakeModel([segment(" world ", .5, 1), segment(" hello ", 0, .5)])
    calls = []
    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return model
    ticks = iter([10, 10.5, 20, 20.25])
    engine = FasterWhisperEngine(Settings(), model_factory=factory, clock=lambda: next(ticks))
    assert calls == []
    request = TranscriptionRequest(audio=audio())
    result = engine.transcribe(request)
    assert result.text == "hello world" and result.language_probability == .87
    assert result.processing_duration == .5 and result.real_time_factor == .5
    assert result.audio_id == request.audio_id
    assert model.closed
    samples, kwargs = model.calls[0]
    assert samples.shape == (16000,) and samples.dtype == np.float32
    assert kwargs == dict(language=None, vad_filter=True, word_timestamps=False, beam_size=5)
    assert calls[0][1] == dict(device="cpu", compute_type="int8", download_root=str(Settings().stt_model_dir), local_files_only=False)
    engine.transcribe(request)
    assert len(calls) == 1
    engine.close()
    assert engine._model is None


@pytest.mark.parametrize("language", ["en", "hi", "mr"])
def test_requested_language_not_reported_as_confidence(language):
    model = FakeModel(language=language)
    engine = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: model)
    result = engine.transcribe(TranscriptionRequest(audio=audio(), language=language))
    assert result.language == language
    assert result.language_probability is None
    assert model.calls[0][1]["language"] == language


def test_unsupported_language():
    model = FakeModel()
    result = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: model).transcribe(
        TranscriptionRequest(audio=audio(), language="zz"))
    assert result.error_code == Code.UNSUPPORTED_LANGUAGE
    assert model.calls == []


def test_optional_words():
    word = SimpleNamespace(word="hello", start=0, end=.5)
    model = FakeModel([segment(words=[word])])
    result = FasterWhisperEngine(Settings(stt_word_timestamps=True),
        model_factory=lambda *a, **k: model).transcribe(TranscriptionRequest(audio=audio()))
    assert result.segments[0].words[0].text == "hello"


@pytest.mark.parametrize("exception,code", [
    (RuntimeError("secret path/token"), Code.MODEL_UNAVAILABLE),
    (PermissionError("secret path/token"), Code.PERMISSION_DENIED),
])
def test_safe_load_errors(exception, code):
    def factory(*args, **kwargs):
        raise exception
    result = FasterWhisperEngine(Settings(), model_factory=factory).transcribe(TranscriptionRequest(audio=audio()))
    assert result.error_code == code
    assert "secret" not in repr(result) and result.text == ""


def test_generator_failure_discards_partial_transcript():
    model = FakeModel()
    def fail():
        yield segment("private partial transcript")
        raise RuntimeError("private internal details")
    model.segments = fail()
    result = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: model).transcribe(TranscriptionRequest(audio=audio()))
    assert result.error_code == Code.TRANSCRIPTION_FAILED
    assert not result.text and not result.segments and model.closed


def test_cancellation_before_load_and_during_segments():
    cancel = Event()
    cancel.set()
    calls = []
    model = FakeModel()
    engine = FasterWhisperEngine(Settings(), model_factory=lambda *a, **k: calls.append(1) or model)
    request = TranscriptionRequest(audio=audio())
    assert engine.transcribe(request, cancel).error_code == Code.CANCELLED
    assert calls == []
    cancel.clear()
    def segments():
        yield segment("discard this")
        cancel.set()
        yield segment("also discard", .5, 1)
    model.segments = segments()
    result = engine.transcribe(request, cancel)
    assert result.error_code == Code.CANCELLED and result.text == ""
    assert model.closed


def test_duration_limit_before_load():
    engine = FasterWhisperEngine(Settings(stt_max_duration_seconds=.5),
        model_factory=lambda *a, **k: pytest.fail("Must not load model"))
    assert engine.transcribe(TranscriptionRequest(audio=audio())).error_code == Code.AUDIO_TOO_LONG


def test_resampling_uses_only_closed_memory_buffer():
    import wave
    buffers = []
    def decoder(buffer):
        buffers.append(buffer)
        with wave.open(buffer, "rb") as source:
            assert (source.getframerate(), source.getnchannels()) == (48000, 1)
        return np.ones(16000, dtype=np.float32) / 32768
    model = FakeModel()
    engine = FasterWhisperEngine(Settings(), decoder=decoder, model_factory=lambda *a, **k: model)
    result = engine.transcribe(TranscriptionRequest(audio=audio(rate=48000, channels=2)))
    assert result.error is None and buffers[0].closed
    assert model.calls[0][0].shape == (16000,)


def test_backend_text_logs_suppressed_and_logger_restored(caplog):
    logger = logging.getLogger("faster_whisper")
    prior = logger.disabled
    def factory(*args, **kwargs):
        logger.error("private transcript")
        return FakeModel()
    with caplog.at_level(logging.DEBUG):
        FasterWhisperEngine(Settings(), model_factory=factory).transcribe(TranscriptionRequest(audio=audio()))
    assert "private transcript" not in caplog.text
    assert logger.disabled == prior


def test_offline_loader_blocks_missing_tokenizer(monkeypatch, tmp_path):
    package, utils = ModuleType("faster_whisper"), ModuleType("faster_whisper.utils")
    loaded, downloads = [], []
    package.WhisperModel = lambda *args, **kwargs: loaded.append((args, kwargs)) or FakeModel()
    def download(name, **kwargs):
        downloads.append(kwargs)
        return str(tmp_path)
    utils.download_model = download
    monkeypatch.setitem(sys.modules, "faster_whisper", package)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    from app.stt.contracts import TranscriptionError
    with pytest.raises(TranscriptionError, match="model_unavailable"):
        load_model("base", device="cpu", compute_type="int8", download_root="models/whisper", local_files_only=True)
    assert loaded == [] and downloads[0]["local_files_only"]
    (tmp_path / "tokenizer.json").write_text("{}")
    load_model("base", device="cpu", compute_type="int8", download_root="models/whisper", local_files_only=True)
    assert loaded[0][1]["local_files_only"] is True
