"""Shared PCM preparation; no gain adjustment, trimming, hardware or persistence."""
import io
import wave

import numpy as np

from app.stt.contracts import TranscriptionError
from app.stt.models import TranscriptionErrorCode as Code


def mono_pcm16(samples):
    """PCM-scale channels to mono using WAV's round-to-even convention."""
    if (not isinstance(samples, np.ndarray) or samples.ndim != 2
            or not len(samples) or not 1 <= samples.shape[1] <= 8
            or samples.dtype not in (np.dtype("int16"), np.dtype("float32"))
            or not np.isfinite(samples).all()):
        raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
    mono = samples.astype(np.float32).mean(axis=1)
    return np.ascontiguousarray(np.rint(mono).clip(-32768, 32767), dtype=np.int16)


def prepare_audio(audio, *, decoder, max_duration):
    """Return finite contiguous float32 mono at 16 kHz; preserve source object."""
    if (audio.samples.dtype != np.int16 or audio.samples.ndim != 2
            or audio.samples.shape[1] != audio.format.channels):
        raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
    if audio.duration > max_duration:
        raise TranscriptionError(Code.AUDIO_TOO_LONG)
    mono = mono_pcm16(audio.samples)
    if audio.format.sample_rate == 16000:
        converted = mono.astype(np.float32) / np.float32(32768.0)
    else:
        # Delegate to the existing decoder; no new resampling dependency.
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(audio.format.sample_rate)
                output.writeframes(mono.astype("<i2", copy=False).tobytes())
            buffer.seek(0)
            converted = decoder(buffer)
    if (not isinstance(converted, np.ndarray) or converted.dtype != np.float32
            or converted.ndim != 1 or not len(converted)
            or len(converted) > 16000 * max_duration
            or not np.isfinite(converted).all()):
        raise TranscriptionError(Code.UNSUPPORTED_AUDIO)
    return np.ascontiguousarray(converted)
