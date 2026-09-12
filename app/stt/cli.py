"""Explicit local transcription sessions; recognized text is never executed."""
import argparse
import math
from pathlib import Path
from time import monotonic

from pydantic import ValidationError

from app.audio.cli import terminal_control
from app.audio.contracts import AudioError
from app.audio.recorder import SoundDeviceRecorder
from app.core.config import Settings, get_settings, normalize_stt_language
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.models import TranscriptionStatus
from app.stt.service import TranscriptionService


def display_result(result, write, *, safety_diagnostics=False):
    if result.status == TranscriptionStatus.CANCELLED:
        write("CANCELLED. Transcript discarded.")
        return 0
    if result.status != TranscriptionStatus.SUCCEEDED:
        write(f"STT error: {result.error_code.value}")
        if result.status == TranscriptionStatus.UNUSABLE_AUDIO:
            write("Safety reasons: " + ", ".join(result.rejection_reasons))
            if safety_diagnostics and result.safety_summary is not None:
                write(result.safety_summary.model_dump_json(indent=2))
        return 1
    # Only sanitize terminal controls; never truncate or rewrite recognized words.
    text = "".join(char if char.isprintable() or char == "\n" else " " for char in result.normalized_transcript)
    write("Transcript: " + (text or "[no speech detected]"))
    write(f"Language: {result.language}")
    if result.language_probability is not None:
        write(f"Language probability: {result.language_probability:.3f} (not transcription confidence)")
    startup = "unknown" if result.cold_start is None else "cold" if result.cold_start else "warm"
    write(f"Start: {startup}; model load (includes download): {result.model_load_duration:.3f}s; inference: {result.inference_duration:.3f}s")
    write(f"Audio: {result.source_audio_duration:.3f}s; processing: {result.processing_duration:.3f}s; RTF: {result.real_time_factor:.3f}")
    return 0


def main(argv=None, *, settings=None, engine=None, recorder=None,
         read=input, write=print, control=terminal_control, clock=monotonic):
    parser = argparse.ArgumentParser(description="Local speech-to-text; no command execution")
    commands = parser.add_subparsers(dest="command", required=True)
    file_parser = commands.add_parser("file", help="Transcribe one explicitly selected PCM WAV")
    file_parser.add_argument("path", type=Path)
    mic_parser = commands.add_parser("microphone", help="Record until Enter, optional silence, or safety maximum")
    mic_parser.add_argument("--seconds", type=float, default=None, help="Optional explicit recording limit")
    mic_parser.add_argument("--silence-seconds", type=float, help="Opt in to stop after this much silence following speech")
    mic_parser.add_argument("--session", action="store_true", help="Repeat deliberate captures using one loaded model")
    for subparser in (file_parser, mic_parser):
        subparser.add_argument("--safety-diagnostics", action="store_true",
                               help="Display numerical rejection evidence only; does not change safety")
        subparser.add_argument("--language", help="Language code such as en, hi, mr, or auto")
    args = parser.parse_args(argv)
    owned_engine = None
    try:
        settings = settings if settings is not None else get_settings()
        if args.language is not None:
            normalize_stt_language(args.language)
        if args.command == "microphone":
            safety = min(settings.audio_max_duration_seconds, settings.stt_max_duration_seconds)
            if args.seconds is not None and (not math.isfinite(args.seconds) or not .1 <= args.seconds <= safety):
                write("STT error: invalid_duration")
                return 2
            changes = {"audio_max_duration_seconds": safety}
            if args.silence_seconds is not None:
                changes.update(audio_silence_stop_enabled=True, audio_silence_duration_seconds=args.silence_seconds)
            settings = Settings.model_validate(settings.model_dump() | changes)
        if not settings.stt_local_files_only:
            write("Model notice: the first transcription may download model files. Audio stays local.")
        if engine is None:
            owned_engine = FasterWhisperEngine(settings)
            engine = owned_engine
        service = TranscriptionService(settings, engine)
        if args.command == "file":
            return display_result(service.transcribe_file(args.path, language=args.language), write,
                                  safety_diagnostics=args.safety_diagnostics)

        recorder = recorder if recorder is not None else SoundDeviceRecorder(settings)
        while True:
            if read("Press Enter to START microphone capture, or type q/c to finish: ").strip():
                write("CANCELLED. No new audio captured or transcribed.")
                return 0
            limit = args.seconds if args.seconds is not None else safety
            write(f"RECORDING requested. Enter stops; c or Ctrl+C cancels. Limit: {limit:g}s. Audio will not be saved.")
            if settings.audio_silence_stop_enabled:
                write(f"Silence stopping enabled: {settings.audio_silence_duration_seconds:g}s after speech.")
            capture_start = clock()
            last_second = -1

            def capture_control():
                nonlocal last_second
                elapsed = max(0, int(clock() - capture_start))
                if elapsed != last_second:
                    write(f"Recording elapsed: {elapsed}s / {limit:g}s")
                    last_second = elapsed
                return control()

            captured = recorder.record(args.seconds, control=capture_control)
            write("RECORDING STOPPED.")
            if captured.status == "cancelled":
                write("CANCELLED. Audio discarded; no transcription.")
                return 0
            if captured.status == "failed":
                write(f"Audio error: {captured.error_code.value}")
                return 1
            write("TRANSCRIBING locally. Ctrl+C requests cancellation.")
            result = service.transcribe_audio(captured.audio, language=args.language)
            # Drop the capture reference before asking for another deliberate action.
            del captured
            code = display_result(result, write, safety_diagnostics=args.safety_diagnostics)
            if code or result.status == TranscriptionStatus.CANCELLED or not args.session:
                return code
            del result
            write("Session ready. The model remains loaded; the microphone is stopped.")
    except (KeyboardInterrupt, EOFError):
        if recorder is not None:
            recorder.cancel()
        write("CANCELLED. Audio/transcript not saved.")
        return 0
    except AudioError as error:
        write(f"Audio error: {error.code.value}")
        return 1
    except (ValidationError, ValueError):
        write("STT error: invalid_configuration")
        return 2
    finally:
        if owned_engine is not None:
            owned_engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
