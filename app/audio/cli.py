"""Explicit terminal push-to-talk; no global keyboard hooks."""
import argparse
import math
import os
import sys

from pydantic import ValidationError

from app.core.config import get_settings
from app.audio.contracts import AudioError, AudioRecorder
from app.audio.devices import list_input_devices
from app.audio.recorder import SoundDeviceRecorder
from app.audio.wav import save_wav


def terminal_control():
    """Poll only this foreground terminal while the user-requested capture runs."""
    if os.name == "nt":
        import msvcrt
        if not msvcrt.kbhit():
            return None
        key = msvcrt.getwch()
    else:
        import select
        if not select.select([sys.stdin], [], [], 0)[0]:
            return None
        key = sys.stdin.readline()
        if key == "":
            return "cancel"
    if key in ("\x03", "\x1b") or key.strip().lower() == "c":
        return "cancel"
    if key in ("\r", "\n"):
        return "stop"
    return None


def main(argv=None, *, recorder: AudioRecorder | None = None, settings=None,
         device_lister=list_input_devices, read=input, write=print,
         control=terminal_control) -> int:
    parser = argparse.ArgumentParser(description="VoicePilot explicit audio input")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List input devices without capturing audio")
    capture = commands.add_parser("record", help="Explicit terminal push-to-talk")
    capture.add_argument("--seconds", type=float, default=3.0)
    capture.add_argument("--save", action="store_true", help="Explicitly permit and request WAV persistence")
    capture.add_argument("--filename", help="Simple .wav filename inside the configured recordings directory")
    capture.add_argument("--overwrite", action="store_true", help="Explicitly allow replacing the selected WAV")
    args = parser.parse_args(argv)
    if args.command == "record" and (args.filename or args.overwrite) and not args.save:
        parser.error("--filename and --overwrite require --save")
    try:
        if args.command == "devices":
            for device in device_lister():
                # Device names are deliberately shown only in this explicit listing.
                name = "".join(char if char.isprintable() else "?" for char in device.name)
                write(f"{device.index}: {name} ({device.max_input_channels} input channels)")
            return 0
        settings = settings if settings is not None else get_settings()
        if not math.isfinite(args.seconds) or not 0.1 <= args.seconds <= settings.audio_max_duration_seconds:
            write("Audio error: invalid_duration")
            return 2
        answer = read("Press Enter to START microphone capture, or type c to cancel: ")
        if answer.strip():
            write("CANCELLED. No audio captured or saved.")
            return 0
        recorder = recorder if recorder is not None else SoundDeviceRecorder(settings)
        write("RECORDING requested. Enter stops; c or Ctrl+C cancels and discards audio. Time limit applies.")
        result = recorder.record(args.seconds, control=control)
        write("RECORDING STOPPED.")
        if result.status == "cancelled":
            write("CANCELLED. Audio discarded; nothing saved.")
            return 0
        if result.status == "failed":
            write(f"Audio error: {result.error_code.value}")
            return 1
        write(f"Captured {result.duration:.3f} seconds in memory.")
        if args.save:
            save_wav(result.audio, settings.recordings_dir, args.filename,
                     persistence_enabled=True, overwrite=args.overwrite)
            write("WAV saved in the configured recordings directory.")
        else:
            write("Nothing saved. In-memory audio is released when this command exits.")
        return 0
    except (KeyboardInterrupt, EOFError):
        if recorder is not None:
            recorder.cancel()
        write("CANCELLED. Audio discarded.")
        return 0
    except AudioError as error:
        write(f"Audio error: {error.code.value}")
        return 1
    except ValidationError:
        write("Audio error: invalid_configuration")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
