"""Explicit single-capture comparison. No recordings, transcripts or hashes saved."""
import argparse
import io
import json
import math
import wave
from threading import Event

import numpy as np

from app.audio.cli import terminal_control
from app.audio.recorder import SoundDeviceRecorder
from app.audio.wav import write_pcm_wav
from app.core.config import Settings, get_settings
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.models import TranscriptionStatus as Status
from app.stt.service import TranscriptionService, read_pcm_wav_stream


class ParitySettings(Settings):
    model_config = {**Settings.model_config, "frozen": True}


def settings_snapshot(settings, language=None):
    changes = {"stt_local_files_only": True}
    if language is not None:
        changes["stt_language"] = language
    return ParitySettings.model_validate(settings.model_dump() | changes)


class ComparisonEngine(FasterWhisperEngine):
    """Keep bounded copies of actual pre-model arrays only during comparison."""
    def __init__(self, settings, **kwargs):
        super().__init__(settings, **kwargs)
        self._path = None
        self._prepared = {}

    def _prepare_audio(self, audio):
        samples = super()._prepare_audio(audio)
        self._prepared[self._path] = samples.copy()
        return samples

    def discard(self):
        for samples in self._prepared.values():
            samples.fill(0)
        self._prepared.clear()
        self._path = None

    def close(self):
        self.discard()
        super().close()


def measurements(samples, rate):
    values = samples.astype(np.float64)
    if samples.dtype == np.int16:
        values /= 32768.0
    return {"dtype": str(samples.dtype), "shape": list(samples.shape),
            "duration": len(samples) / rate,
            "rms": float(np.sqrt(np.mean(values * values))),
            "peak": float(np.max(np.abs(values)))}


def result_measurements(result):
    summary = result.safety_summary
    return {
        "status": result.status.value,
        "rejection_reasons": list(result.rejection_reasons),
        "duration_after_vad": summary.duration_after_vad if summary else result.duration_after_vad,
        "segment_count": summary.original_segment_count if summary else
                         (len(result.segments) if result.status == Status.SUCCEEDED else None),
        "processing_duration": result.processing_duration,
        "model_load_duration": result.model_load_duration,
        "inference_duration": result.inference_duration,
    }


def compare_capture(audio, engine, *, reverse=False, show_successful_transcripts=False, cancel=None):
    """Return only an allowlisted report; cancellation returns no measurements."""
    cancel = cancel if cancel is not None else Event()
    if not isinstance(engine.settings, ParitySettings) or not engine.settings.stt_local_files_only:
        raise ValueError("invalid_parity_settings")
    engine.discard()
    results = {}
    loaded = first = second = None
    try:
        if cancel.is_set():
            return None
        with io.BytesIO() as buffer:
            write_pcm_wav(audio, buffer)
            buffer.seek(0)
            with wave.open(buffer, "rb") as wav:
                preserved = (wav.getframerate() == audio.format.sample_rate
                             and wav.getnchannels() == audio.format.channels
                             and wav.getsampwidth() == 2
                             and wav.getnframes() == len(audio.samples)
                             and wav.readframes(wav.getnframes()) ==
                             audio.samples.astype("<i2", copy=False).tobytes())
            if not preserved:
                raise ValueError("pcm_roundtrip_mismatch")
            buffer.seek(0)
            loaded = read_pcm_wav_stream(buffer, engine.settings.stt_max_duration_seconds)
        if cancel.is_set():
            return None
        service = TranscriptionService(engine.settings, engine)
        order = ("wav", "direct") if reverse else ("direct", "wav")
        for path in order:
            engine._path = path
            results[path] = service.transcribe_audio(audio if path == "direct" else loaded, cancel=cancel)
            if cancel.is_set() or results[path].status == Status.CANCELLED:
                return None
        first, second = engine._prepared.get("direct"), engine._prepared.get("wav")
        comparable = first is not None and second is not None and first.shape == second.shape
        both_succeeded = all(result.status == Status.SUCCEEDED for result in results.values())
        report = {
            "source": {"sample_rate": audio.format.sample_rate, "channel_count": audio.format.channels,
                       "frame_count": len(audio.samples), **measurements(audio.samples, audio.format.sample_rate)},
            "pcm16_preserved": preserved,
            "prepared": {path: measurements(samples, 16000) for path, samples in engine._prepared.items()},
            "prepared_equal": bool(np.array_equal(first, second)) if first is not None and second is not None else None,
            "max_absolute_difference": float(np.max(np.abs(first - second))) if comparable else None,
            "stt": {path: result_measurements(results[path]) for path in order},
            "transcription_equal": (results["direct"].normalized_transcript == results["wav"].normalized_transcript)
                                   if both_succeeded else None,
        }
        if show_successful_transcripts:
            report["successful_transcripts"] = {
                path: result.normalized_transcript for path, result in results.items()
                if result.status == Status.SUCCEEDED
            }
        return None if cancel.is_set() else report
    finally:
        engine.discard()
        results.clear()
        audio = loaded = first = second = None


def main(argv=None, *, settings=None, recorder=None, engine_factory=ComparisonEngine,
         read=input, write=print, control=terminal_control, cancel=None):
    parser = argparse.ArgumentParser(description="Capture once; compare direct and memory-WAV STT. Never saves audio.")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--language")
    parser.add_argument("--contextual", action="store_true")
    parser.add_argument("--reverse-order", action="store_true")
    parser.add_argument("--show-successful-transcripts", action="store_true")
    args = parser.parse_args(argv)
    engine = captured = report = None
    cancel = cancel if cancel is not None else Event()
    try:
        snapshot = settings_snapshot(settings if settings is not None else get_settings(), args.language)
        if args.contextual:
            snapshot = ParitySettings.model_validate(snapshot.model_dump() | {"stt_contextual_enabled": True})
        limit = min(snapshot.audio_max_duration_seconds, snapshot.stt_max_duration_seconds)
        if not math.isfinite(args.seconds) or not .1 <= args.seconds <= limit:
            write("Parity error: invalid_duration")
            return 2
        if cancel.is_set() or read("Press Enter to START one capture and two local STT calls; any text cancels: ") != "":
            write("CANCELLED. No comparison retained.")
            return 0
        recorder = recorder if recorder is not None else SoundDeviceRecorder(snapshot)
        write("RECORDING. Enter stops; c/Ctrl+C cancels. Audio stays in memory.")
        def capture_control():
            return "cancel" if cancel.is_set() else control()
        captured = recorder.record(args.seconds, control=capture_control)
        if cancel.is_set() or captured.status == "cancelled":
            write("CANCELLED. No comparison retained.")
            return 0
        if captured.status != "succeeded":
            write("Parity error: capture_failed")
            return 1
        engine = engine_factory(snapshot)
        report = compare_capture(captured.audio, engine, reverse=args.reverse_order,
                                 show_successful_transcripts=args.show_successful_transcripts, cancel=cancel)
        if report is None or cancel.is_set():
            write("CANCELLED. No comparison retained.")
            return 0
        write(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
        return 0 if all(item["status"] == "succeeded" for item in report["stt"].values()) else 1
    except (KeyboardInterrupt, EOFError):
        cancel.set()
        if recorder is not None:
            recorder.cancel()
        write("CANCELLED. No comparison retained.")
        return 0
    except Exception:
        # Backend/validation exceptions may contain samples or transcript text.
        write("Parity error: comparison_failed")
        return 1
    finally:
        captured = report = None
        if engine is not None:
            engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
