"""Bounded, cancellable PCM capture. No device access on import or construction."""
import math
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic

import numpy as np

from app.core import timing
from app.core.config import Settings
from app.audio.contracts import AudioError, Control
from app.audio.devices import error_code, load_backend, select_input_device
from app.audio.models import (
    AudioFormat, ErrorCode, RecordedAudio, RecordingResult, RecordingState,
)


class SoundDeviceRecorder:
    def __init__(self, settings: Settings, *, backend=None, clock=monotonic):
        self.settings = settings
        self.format = AudioFormat(sample_rate=settings.audio_sample_rate,
                                  channels=settings.audio_channels,
                                  dtype=settings.audio_dtype)
        self._backend = backend
        self._clock = clock
        self._guard = Lock()
        self._stop = Event()
        self._cancel = Event()
        self._state = RecordingState.IDLE

    @property
    def state(self) -> RecordingState:
        return self._state

    def stop(self) -> None:
        self._stop.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._stop.set()

    def record(self, duration_seconds: float | None = None,
               control: Control | None = None, *, guard=None, capture_stage="capture") -> RecordingResult:
        duration = self.settings.audio_max_duration_seconds if duration_seconds is None else duration_seconds
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or not 0.1 <= duration <= self.settings.audio_max_duration_seconds):
            raise AudioError(ErrorCode.INVALID_DURATION)
        if not self._guard.acquire(blocking=False):
            raise AudioError(ErrorCode.BUSY)
        self._stop.clear()
        self._cancel.clear()
        started = datetime.now(timezone.utc)
        device = None
        stream = None
        chunks = []
        frames_captured = 0
        silent_frames = 0
        heard_speech = False
        max_frames = int(duration * self.format.sample_rate)
        done = Event()
        failure = None
        self._state = RecordingState.RECORDING
        from app.execution.cancellation import GLOBAL, CallbackSignal
        cancellation_context = GLOBAL.track(CallbackSignal(self.cancel))
        cancellation_context.__enter__()
        try:
            if self._cancel.is_set():
                raise AudioError(ErrorCode.CANCELLED)
            with timing.span("recorder_setup"):
                backend = self._backend if self._backend is not None else load_backend()
                device = select_input_device(self.settings.audio_input_device, backend)
                if device.max_input_channels < self.format.channels:
                    raise AudioError(ErrorCode.DEVICE_UNAVAILABLE)
                backend.check_input_settings(device=device.index,
                                             samplerate=self.format.sample_rate,
                                             channels=self.format.channels,
                                             dtype=self.format.dtype)

            def callback(indata, frames, time_info, status):
                nonlocal frames_captured, failure, silent_frames, heard_speech
                if self._stop.is_set():
                    done.set()
                    raise backend.CallbackStop
                try:
                    if status:
                        failure = ErrorCode.INPUT_OVERFLOW
                        done.set()
                    else:
                        count = min(frames, max_frames - frames_captured)
                        pcm = np.frombuffer(indata, dtype=np.int16).reshape(frames, self.format.channels)
                        chunks.append(pcm[:count].copy())
                        frames_captured += count
                        if self.settings.audio_silence_stop_enabled and count:
                            level = pcm[:count].astype(np.float32) / 32768.0
                            rms = float(np.sqrt(np.mean(level * level)))
                            if rms >= self.settings.audio_silence_threshold:
                                heard_speech = True
                                silent_frames = 0
                            elif heard_speech:
                                silent_frames += count
                                if silent_frames >= self.settings.audio_silence_duration_seconds * self.format.sample_rate:
                                    done.set()
                        if frames_captured >= max_frames:
                            done.set()
                except Exception:
                    failure = ErrorCode.STREAM_FAILED
                    done.set()
                if done.is_set():
                    raise backend.CallbackStop

            if guard is not None:
                guard()  # Device discovery may have consumed the caller deadline.
            with timing.span("recorder_setup"):
                stream = backend.RawInputStream(
                    samplerate=self.format.sample_rate, channels=self.format.channels,
                    dtype=self.format.dtype, blocksize=self.settings.audio_block_size,
                    device=device.index, callback=callback, finished_callback=done.set,
                )
            deadline = self._clock() + duration
            if guard is not None:
                guard()  # Never start a stream after slow native construction.
            with timing.span(capture_stage):
                stream.start()
                while not done.is_set() and not self._stop.is_set():
                    if control is not None:
                        action = control()
                        if action == "cancel":
                            self.cancel()
                        elif action == "stop":
                            self.stop()
                    if self._clock() >= deadline:
                        self.stop()
                    if not self._stop.is_set():
                        done.wait(0.02)
        except KeyboardInterrupt:
            self.cancel()
        except Exception as error:
            failure = error_code(error)
        finally:
            if stream is not None:
                try:
                    stream.abort()
                except Exception:
                    failure = ErrorCode.STREAM_FAILED
                finally:
                    try:
                        stream.close()
                    except Exception:
                        failure = ErrorCode.STREAM_FAILED

        # Streams are closed before samples are assembled or cancellation is reported.
        try:
            audio = None
            if self._cancel.is_set():
                status, failure = "cancelled", ErrorCode.CANCELLED
            elif failure is not None:
                status = "failed"
            elif not frames_captured:
                status, failure = "failed", ErrorCode.NO_AUDIO
            else:
                status = "succeeded"
                try:
                    audio = RecordedAudio(format=self.format, samples=np.concatenate(chunks))
                except Exception:
                    status, failure = "failed", ErrorCode.STREAM_FAILED
            self._state = RecordingState(status)
            return RecordingResult(
                format=self.format, audio=audio, started_at=started,
                ended_at=max(started, datetime.now(timezone.utc)), device=device,
                status=status, error_code=failure,
            )
        finally:
            chunks.clear()
            cancellation_context.__exit__(None, None, None)
            self._guard.release()
