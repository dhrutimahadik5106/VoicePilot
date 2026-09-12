"""Lazy local Faster-Whisper adapter; no model/audio/transcript logging."""
import logging
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, RLock
from time import perf_counter

from app.stt.audio_preprocessing import prepare_audio
from app.core.config import Settings
from app.stt.output_safety import OutputBudget, apply_output_safety, reject, _number
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

    def failure(self, request, code, elapsed=0.0, **timings):
        return TranscriptionResult(
            audio_id=request.audio_id, execution_correlation_id=request.execution_correlation_id,
            language=request.language, processing_duration=elapsed, **timings,
            source_audio_duration=request.audio.duration,
            model_name=self.settings.whisper_model, device=self.settings.whisper_device,
            compute_type=self.settings.whisper_compute_type,
            status=TranscriptionStatus.CANCELLED if code == Code.CANCELLED else TranscriptionStatus.FAILED,
            error=SafeTranscriptionError(code=code),
        )

    def _prepare_audio(self, audio):
        return prepare_audio(audio, decoder=self._decoder,
                             max_duration=self.settings.stt_max_duration_seconds)

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
        model_load_duration = 0.0
        inference_duration = 0.0
        load_started = None
        inference_started = None
        cold_start = None
        try:
            with quiet_backend():
                samples = self._prepare_audio(request.audio)
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                cold_start = self._model is None
                if cold_start:
                    stage = "load"
                    load_started = self._clock()
                    self._model = self._factory(
                        self.settings.whisper_model, device=self.settings.whisper_device,
                        compute_type=self.settings.whisper_compute_type,
                        download_root=str(self.settings.stt_model_dir),
                        local_files_only=self.settings.stt_local_files_only,
                    )
                    model_load_duration = max(0.0, self._clock() - load_started)
                    load_started = None
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                stage = "transcribe"
                if request.language is not None and request.language not in self._model.supported_languages:
                    raise TranscriptionError(Code.UNSUPPORTED_LANGUAGE)
                inference_started = self._clock()
                stream, info = self._model.transcribe(
                    samples, language=request.language, vad_filter=self.settings.stt_vad_filter,
                    word_timestamps=self.settings.stt_word_timestamps,
                    beam_size=self.settings.stt_beam_size,
                    temperature=self.settings.stt_temperature,
                    vad_parameters={"min_silence_duration_ms": self.settings.stt_vad_min_silence_duration_ms,
                                    "speech_pad_ms": 400},
                    initial_prompt=self.settings.stt_initial_prompt or None,
                    hotwords=self.settings.stt_hotwords or None,
                )
                segments = []
                budget = OutputBudget(self.settings)
                for segment in stream:
                    if cancel is not None and cancel.is_set():
                        raise TranscriptionError(Code.CANCELLED)
                    if not budget.add(segment.text, segment):
                        break
                    words = ()
                    if self.settings.stt_word_timestamps and segment.words:
                        words = tuple(WordTimestamp(text=word.word, start=word.start, end=word.end)
                                      for word in segment.words)
                    segments.append(TranscriptSegment(
                        text=segment.text, start=segment.start, end=segment.end, words=words,
                        no_speech_prob=getattr(segment, "no_speech_prob", None),
                        avg_logprob=getattr(segment, "avg_logprob", None),
                    ))
                if cancel is not None and cancel.is_set():
                    raise TranscriptionError(Code.CANCELLED)
                inference_duration = max(0.0, self._clock() - inference_started)
                inference_started = None
                segments.sort(key=lambda segment: (segment.start, segment.end))
                if budget.exhausted:
                    result = self.failure(
                        request, Code.UNUSABLE_AUDIO, max(0.0, self._clock() - started),
                        model_load_duration=model_load_duration,
                        inference_duration=inference_duration, cold_start=cold_start,
                    )
                    return apply_output_safety(
                        reject(result, ("output_budget_exceeded",),
                               budget.summary(("output_budget_exceeded",), request.audio.duration,
                                              getattr(info, "duration_after_vad", None))),
                        self.settings, cancel,
                    )
                result = TranscriptionResult(
                    audio_id=request.audio_id, execution_correlation_id=request.execution_correlation_id,
                    text=" ".join(segment.text.strip() for segment in segments if segment.text.strip()),
                    language=info.language,
                    # Explicit-language probability=1 is a backend placeholder, not detection.
                    language_probability=info.language_probability if request.language is None else None,
                    segments=tuple(segments), processing_duration=max(0.0, self._clock() - started),
                    model_load_duration=model_load_duration, inference_duration=inference_duration,
                    cold_start=cold_start, source_audio_duration=request.audio.duration,
                    duration_after_vad=_number(getattr(info, "duration_after_vad", None), nonnegative=True),
                    model_name=self.settings.whisper_model, device=self.settings.whisper_device,
                    compute_type=self.settings.whisper_compute_type, status=TranscriptionStatus.SUCCEEDED,
                )
                result = apply_output_safety(result, self.settings, cancel,
                                             duration_after_vad=getattr(info, "duration_after_vad", None))
                return result
        except (Exception, KeyboardInterrupt) as error:
            if isinstance(error, KeyboardInterrupt):
                code = Code.CANCELLED
            elif isinstance(error, TranscriptionError):
                code = error.code
            elif isinstance(error, PermissionError):
                code = Code.PERMISSION_DENIED
            else:
                code = Code.MODEL_UNAVAILABLE if stage == "load" else Code.TRANSCRIPTION_FAILED
            ended = self._clock()
            if load_started is not None:
                model_load_duration = max(0.0, ended - load_started)
            if inference_started is not None:
                inference_duration = max(0.0, ended - inference_started)
            return self.failure(
                request, code, max(0.0, ended - started),
                model_load_duration=model_load_duration, inference_duration=inference_duration,
                cold_start=cold_start,
            )
        finally:
            try:
                if stream is not None and hasattr(stream, "close"):
                    with quiet_backend():
                        stream.close()
            except Exception:
                pass  # Do not leak generator/native exception text during cleanup.
            finally:
                self._guard.release()
