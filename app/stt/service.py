"""Validate explicitly selected inputs; never scan folders or persist audio."""
import stat
import wave
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import numpy as np

from app.audio.models import AudioFormat, RecordedAudio
from app.core.config import Settings
from app.stt.output_safety import apply_output_safety
from app.stt.contracts import SpeechToTextEngine, TranscriptionError
from app.stt.models import (
    SafeTranscriptionError, TranscriptionErrorCode as Code, TranscriptionRequest,
    TranscriptionResult, TranscriptionStatus,
)


def read_pcm_wav(path: Path, max_duration: float) -> RecordedAudio:
    """Read only the selected regular WAV: 8/16/24/32-bit PCM, 1-8 channels."""
    try:
        path = Path(path)
        if path.suffix.lower() != ".wav":
            raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
        if not stat.S_ISREG(path.stat().st_mode):
            raise TranscriptionError(Code.INVALID_WAV)
        # Bound container size as well as header-declared PCM duration.
        if path.stat().st_size > 48000 * 8 * 4 * max_duration + 65536:
            raise TranscriptionError(Code.AUDIO_TOO_LONG)
        with path.open("rb") as source:
            with wave.open(source, "rb") as wav:
                rate, channels, width, count = wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
                if wav.getcomptype() != "NONE" or not 8000 <= rate <= 48000 or not 1 <= channels <= 8 or width not in (1, 2, 3, 4):
                    raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
                if count == 0:
                    raise TranscriptionError(Code.EMPTY_AUDIO)
                if count / rate > max_duration:
                    raise TranscriptionError(Code.AUDIO_TOO_LONG)
                raw = wav.readframes(count)
                if len(raw) != count * channels * width:
                    raise TranscriptionError(Code.INVALID_WAV)
        if width == 1:
            pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) * 256
        elif width == 2:
            pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32)
        elif width == 3:
            octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            integers = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
            integers = (integers ^ 0x800000) - 0x800000
            pcm = integers.astype(np.float32) / 256
        else:
            pcm = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 65536
        mono = np.rint(pcm.reshape(-1, channels).mean(axis=1)).clip(-32768, 32767).astype(np.int16)
        return RecordedAudio(format=AudioFormat(sample_rate=rate), samples=mono[:, None])
    except TranscriptionError:
        raise
    except FileNotFoundError:
        raise TranscriptionError(Code.FILE_NOT_FOUND) from None
    except PermissionError:
        raise TranscriptionError(Code.PERMISSION_DENIED) from None
    except (OSError, ValueError, EOFError, wave.Error):
        raise TranscriptionError(Code.INVALID_WAV) from None


class TranscriptionService:
    def __init__(self, settings: Settings, engine: SpeechToTextEngine):
        self.settings = settings
        self.engine = engine

    def transcribe_audio(self, audio: RecordedAudio, *, language=None,
                         cancel: Event | None = None, audio_id: UUID | None = None,
                         execution_correlation_id: UUID | None = None) -> TranscriptionResult:
        request = TranscriptionRequest(
            audio=audio, language=self.settings.stt_language if language is None else language,
            audio_id=audio_id or uuid4(), execution_correlation_id=execution_correlation_id,
        )
        if cancel is not None and cancel.is_set():
            return self._failure(request.audio_id, Code.CANCELLED, audio.duration, execution_correlation_id)
        if audio.duration > self.settings.stt_max_duration_seconds:
            return self._failure(request.audio_id, Code.AUDIO_TOO_LONG, audio.duration, execution_correlation_id)
        result = self.engine.transcribe(request, cancel=cancel)
        # Duration is measured from the supplied PCM, not trusted engine metadata.
        result = result.model_copy(update={"source_audio_duration": audio.duration})
        if result.safety_summary is not None:
            summary = result.safety_summary.model_copy(update={
                "actual_audio_duration": audio.duration,
                "token_limit": max(self.settings.stt_safety_min_tokens,
                                   self.settings.stt_safety_tokens_per_second * audio.duration),
                "character_limit": max(self.settings.stt_safety_min_characters,
                                       self.settings.stt_safety_characters_per_second * audio.duration),
            })
            result = result.model_copy(update={"safety_summary": summary})
        return apply_output_safety(result, self.settings, cancel)

    def transcribe_file(self, path: Path, *, language=None, cancel: Event | None = None,
                        audio_id: UUID | None = None, execution_correlation_id: UUID | None = None):
        identifier = audio_id or uuid4()
        if cancel is not None and cancel.is_set():
            return self._failure(identifier, Code.CANCELLED, correlation=execution_correlation_id)
        try:
            audio = read_pcm_wav(path, self.settings.stt_max_duration_seconds)
        except TranscriptionError as error:
            return self._failure(identifier, error.code, correlation=execution_correlation_id)
        return self.transcribe_audio(audio, language=language, cancel=cancel,
                                     audio_id=identifier, execution_correlation_id=execution_correlation_id)

    def _failure(self, identifier, code, duration=0.0, correlation=None):
        return TranscriptionResult(
            audio_id=identifier, execution_correlation_id=correlation,
            processing_duration=0.0, source_audio_duration=duration,
            model_name=self.settings.whisper_model, device=self.settings.whisper_device,
            compute_type=self.settings.whisper_compute_type,
            status=TranscriptionStatus.CANCELLED if code == Code.CANCELLED else TranscriptionStatus.FAILED,
            error=SafeTranscriptionError(code=code),
        )
