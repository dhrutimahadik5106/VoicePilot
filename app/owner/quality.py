"""Conservative energy activity gate, not a speech or liveness classifier."""
import numpy as np
from app.speaker.quality import NumericalQuality
from app.owner.models import OwnerError


def check_audio(audio, speaker_cfg, owner_cfg):
    quality = NumericalQuality(speaker_cfg).assess(audio)
    if not quality.eligible or audio.format.channels != 1:
        raise OwnerError("capture_quality_failed")
    values = audio.samples[:, 0].astype(np.float64) / 32768
    size = 320  # fixed 20 ms at the required 16 kHz
    frames = values[:len(values) // size * size].reshape(-1, size)
    active = np.sqrt(np.mean(frames * frames, axis=1)) >= speaker_cfg.min_rms
    if (not len(active) or float(active.mean()) < owner_cfg.minimum_active_fraction
            or int(active.sum()) * .02 < owner_cfg.minimum_active_seconds):
        raise OwnerError("capture_quality_failed")



def check_speech_duration(transcript, owner_cfg):
    # Use existing decoder VAD metadata when present, without changing its thresholds.
    summary = getattr(transcript, "safety_summary", None)
    duration = getattr(summary, "duration_after_vad", None)
    if duration is not None and duration < owner_cfg.minimum_active_seconds:
        raise OwnerError("capture_quality_failed")
