"""Lazy local Faster-Whisper adapter; no model/audio/transcript logging."""
import io
import logging
import wave
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, RLock
from time import perf_counter

import numpy as np

from app.core.config import Settings
from app.stt.contracts import TranscriptionError
from app.stt.models import (
    SafeTranscriptionError, TranscriptSegment, TranscriptionErrorCode as Code,
    TranscriptionRequest, TranscriptionResult, TranscriptionStatus, WordTimestamp,
)

_LOG_GUARD = RLock()


@contextmanager
def quiet_backend():
    # Faster-Whisper DEBUG logs can contain decoded text; suppress at the producer.
    with _LOG_GUARD:
        logger = logging.getLogger("faster_whisper")
        previous = logger.disabled
        logger.disabled = True
        try:
            yield
        finally:
            logger.disabled = previous


def load_model(name, *, device, compute_type, download_root, local_files_only):
    """Called only by an explicit transcription, never at import/startup."""
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    # Resolve the complete snapshot first. A missing tokenizer must not trigger
    # WhisperModel's fallback network fetch when offline mode was requested.
    path = download_model(name, cache_dir=download_root, local_files_only=local_files_only)
    if not (Path(path) / "tokenizer.json").is_file():
        raise TranscriptionError(Code.MODEL_UNAVAILABLE)
    return WhisperModel(path, device=device, compute_type=compute_type, local_files_only=True)


def decode_resampled(wav_buffer):
    from faster_whisper.audio import decode_audio
    return decode_audio(wav_buffer, sampling_rate=16000)


class FasterWhisperEngine:
    def __init__(self, settings: Settings, *, model_factory=load_model,
                 decoder=decode_resampled, clock=perf_counter):
        self.settings = settings
        self._factory = model_factory
        self._decoder = decoder
        self._clock = clock
        self._model = None
        self._guard = Lock()

    def close(self):
        """Drop the cached model reference; native resources follow library lifetime."""
        with self._guard:
            self._model = None

    def failure(self, request, code, elapsed=0.0):
        return TranscriptionResult(
            audio_id=request.audio_id, execution_correlation_id=request.execution_correlation_id,
            language=request.language, processing_duration=elapsed,
            source_audio_duration=request.audio.duration,
            model_name=self.settings.whisper_model, device=self.settings.whisper_device,
            compute_type=self.settings.whisper_compute_type,
            status=TranscriptionStatus.CANCELLED if code == Code.CANCELLED else TranscriptionStatus.FAILED,
            error=SafeTranscriptionError(code=code),
        )

    def _prepare_audio(self, audio):
        mono = audio.samples.astype(np.float32).mean(axis=1)
        if audio.format.sample_rate == 16000:
            return mono / np.float32(32768.0)
        # Keep temporary WAV bytes entirely in memory. PyAV's resampler is
        # supplied by Faster-Whisper; do not add a resampling dependency.
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(audio.format.sample_rate)
                output.writeframes(np.rint(mono).clip(-32768, 32767).astype("<i2").tobytes())
            buffer.seek(0)
            converted = self._decoder(buffer)
        if (not isinstance(converted, np.ndarray) or converted.dtype != np.float32
                or converted.ndim != 1 or not len(converted)
                or len(converted) > 16000 * self.settings.stt_max_duration_seconds
                or not np.isfinite(converted).all()):
            raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
        return converted

    def transcribe(self, request: TranscriptionRequest,
                   cancel: Event | None = None) -> TranscriptionResult:
        if cancel is not None and cancel.is_set():
            return self.failure(request, Code.CANCELLED)
        if request.audio.duration > self.settings.stt_max_duration_seconds:
            return self.failure(request, Code.AUDIO_TOO_LONG)
        if not self._guard.acquire(blocking=False):
            return self.failure(request, Code.BUSY)
        started = self._clock()
        stream = None
        stage = "prepare"
        try:
            with quiet_backend():
                samples = self._prepare_audio(request.audio)
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                if self._model is None:
                    stage = "load"
                    self._model = self._factory(
                        self.settings.whisper_model, device=self.settings.whisper_device,
                        compute_type=self.settings.whisper_compute_type,
                        download_root=str(self.settings.stt_model_dir),
                        local_files_only=self.settings.stt_local_files_only,
                    )
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                stage = "transcribe"
                if request.language is not None and request.language not in self._model.supported_languages:
                    raise TranscriptionError(Code.UNSUPPORTED_LANGUAGE)
                stream, info = self._model.transcribe(
                    samples, language=request.language, vad_filter=self.settings.stt_vad_filter,
                    word_timestamps=self.settings.stt_word_timestamps,
                    beam_size=self.settings.stt_beam_size,
                )
                segments = []
                for segment in stream:
                    if cancel is not None and cancel.is_set():
                        raise TranscriptionError(Code.CANCELLED)
                    words = ()
                    if self.settings.stt_word_timestamps and segment.words:
                        words = tuple(WordTimestamp(text=word.word, start=word.start, end=word.end)
                                      for word in segment.words)
                    segments.append(TranscriptSegment(
                        text=segment.text, start=segment.start, end=segment.end, words=words,
                    ))
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                segments.sort(key=lambda segment: (segment.start, segment.end))
                return TranscriptionResult(
                    audio_id=request.audio_id, execution_correlation_id=request.execution_correlation_id,
                    text=" ".join(segment.text.strip() for segment in segments if segment.text.strip()),
                    language=info.language,
                    # Explicit-language probability=1 is a backend placeholder, not detection.
                    language_probability=info.language_probability if request.language is None else None,
                    segments=tuple(segments), processing_duration=max(0.0, self._clock() - started),
                    source_audio_duration=request.audio.duration,
                    model_name=self.settings.whisper_model, device=self.settings.whisper_device,
                    compute_type=self.settings.whisper_compute_type, status=TranscriptionStatus.SUCCEEDED,
                )
        except KeyboardInterrupt:
            return self.failure(request, Code.CANCELLED, max(0.0, self._clock() - started))
        except Exception as error:
            if isinstance(error, TranscriptionError):
                code = error.code
            elif isinstance(error, PermissionError):
                code = Code.PERMISSION_DENIED
            else:
                code = Code.MODEL_UNAVAILABLE if stage == "load" else Code.TRANSCRIPTION_FAILED
            return self.failure(request, code, max(0.0, self._clock() - started))
        finally:
            try:
                if stream is not None and hasattr(stream, "close"):
                    with quiet_backend():
                        stream.close()
            except Exception:
                pass  # Do not leak generator/native exception text during cleanup.
            finally:
                self._guard.release()
