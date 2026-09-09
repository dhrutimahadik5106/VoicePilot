"""Explicit local transcription; recognized text is displayed, never executed."""
import argparse
import math
from pathlib import Path

from pydantic import ValidationError

from app.audio.cli import terminal_control
from app.audio.contracts import AudioError
from app.audio.recorder import SoundDeviceRecorder
from app.core.config import get_settings, normalize_stt_language
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.models import TranscriptionStatus
from app.stt.service import TranscriptionService


def main(argv=None, *, settings=None, engine=None, recorder=None,
         read=input, write=print, control=terminal_control):
    parser = argparse.ArgumentParser(description="Local speech-to-text; no command execution")
    commands = parser.add_subparsers(dest="command", required=True)
    file_parser = commands.add_parser("file", help="Transcribe one explicitly selected PCM WAV")
    file_parser.add_argument("path", type=Path)
    mic_parser = commands.add_parser("microphone", help="Record with explicit consent and transcribe in memory")
    mic_parser.add_argument("--seconds", type=float, default=5)
    for subparser in (file_parser, mic_parser):
        subparser.add_argument("--language", help="Language code such as en, hi, mr, or auto")
    args = parser.parse_args(argv)
    owned_engine = None
    try:
        settings = settings if settings is not None else get_settings()
        if args.language is not None:
            normalize_stt_language(args.language)
        if args.command == "microphone":
            if (not math.isfinite(args.seconds) or not .1 <= args.seconds
                    <= min(settings.audio_max_duration_seconds, settings.stt_max_duration_seconds)):
                write("STT error: invalid_duration")
                return 2
        if not settings.stt_local_files_only:
            write("Model notice: the first transcription may download model files. Audio stays local.")
        if engine is None:
            owned_engine = FasterWhisperEngine(settings)
            engine = owned_engine
        service = TranscriptionService(settings, engine)
        if args.command == "file":
            result = service.transcribe_file(args.path, language=args.language)
        else:
            if read("Press Enter to START microphone capture, or type c to cancel: ").strip():
                write("CANCELLED. No audio captured or transcribed.")
                return 0
            recorder = recorder if recorder is not None else SoundDeviceRecorder(settings)
            write("RECORDING requested. Enter stops; c or Ctrl+C cancels. Audio will not be saved.")
            captured = recorder.record(args.seconds, control=control)
            write("RECORDING STOPPED.")
            if captured.status == "cancelled":
                write("CANCELLED. Audio discarded; no transcription.")
                return 0
            if captured.status == "failed":
                write(f"Audio error: {captured.error_code.value}")
                return 1
            write("TRANSCRIBING locally. Ctrl+C requests cancellation.")
            result = service.transcribe_audio(captured.audio, language=args.language)
        if result.status == TranscriptionStatus.CANCELLED:
            write("CANCELLED. Transcript discarded.")
            return 0
        if result.status == TranscriptionStatus.FAILED:
            write(f"STT error: {result.error_code.value}")
            return 1
        # Remove terminal escape/control characters, not natural-language content.
        text = "".join(char if char.isprintable() or char == "\n" else " " for char in result.text)
        write("Transcript: " + (text or "[no speech detected]"))
        write(f"Language: {result.language}")
        if result.language_probability is not None:
            write(f"Language probability: {result.language_probability:.3f} (not transcription confidence)")
        write(f"Audio: {result.source_audio_duration:.3f}s; processing: {result.processing_duration:.3f}s; RTF: {result.real_time_factor:.3f}")
        return 0
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
