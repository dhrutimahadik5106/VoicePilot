"""Explicit PCM WAV export confined to the project's ignored recordings tree."""
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import validate_recordings_dir
from app.audio.contracts import AudioError
from app.audio.models import ErrorCode, RecordedAudio


def save_wav(audio: RecordedAudio, directory: Path = Path("recordings"),
             filename: str | None = None, *, persistence_enabled: bool = False,
             overwrite: bool = False) -> Path:
    if not persistence_enabled:
        raise AudioError(ErrorCode.PERSISTENCE_DISABLED)
    try:
        directory = validate_recordings_dir(directory)
        root = Path.cwd().resolve()
        destination_dir = root / directory
        # Disallow symlinks/junctions, including existing parent components.
        current = root
        for part in directory.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                raise ValueError("Linked destination")
        if not destination_dir.resolve().is_relative_to(root / "recordings"):
            raise ValueError("Destination escapes recordings")
        if filename is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            filename = f"capture-{stamp}-{uuid4().hex[:8]}.wav"
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\.wav", filename)
                or filename.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
                 *{f"LPT{i}" for i in range(1, 10)}}):
            raise ValueError("Invalid filename")
        target = destination_dir / filename
        if target.is_symlink() or target.is_junction():
            raise ValueError("Linked file")
    except (ValueError, TypeError, OSError):
        raise AudioError(ErrorCode.INVALID_DESTINATION) from None
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        with target.open("wb" if overwrite else "xb") as handle:
            with wave.open(handle, "wb") as output:
                output.setnchannels(audio.format.channels)
                output.setsampwidth(2)
                output.setframerate(audio.format.sample_rate)
                output.writeframes(audio.samples.astype("<i2", copy=False).tobytes())
        return target
    except FileExistsError:
        raise AudioError(ErrorCode.FILE_EXISTS) from None
    except OSError:
        raise AudioError(ErrorCode.EXPORT_FAILED) from None
