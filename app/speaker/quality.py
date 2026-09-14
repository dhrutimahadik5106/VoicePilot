"""Engineering signal checks only; no speech, mixture or liveness detector."""
import numpy as np
from app.audio.models import RecordedAudio
from app.speaker.models import SpeakerConfiguration, SpeakerQualitySummary

class NumericalQuality:
    def __init__(self, configuration: SpeakerConfiguration):
        self.configuration = configuration
    def assess(self, audio):
        bad = SpeakerQualitySummary(eligible=False)
        try:
            if not isinstance(audio, RecordedAudio):
                return bad
            cfg, pcm = self.configuration, audio.samples
            if (pcm.dtype != np.int16 or pcm.ndim != 2 or not len(pcm)
                    or pcm.shape[1] != audio.format.channels or pcm.shape[1] not in (1, 2)
                    or audio.format.sample_rate != cfg.sample_rate):
                return bad
            values = pcm.astype(np.float64) / 32768.0
            if not np.isfinite(values).all():
                return bad
            # Gate both original channels and mono; opposite channels must not pass as silence.
            mono = values.mean(axis=1)
            rms = float(np.sqrt(np.mean(mono ** 2)))
            peak = float(np.max(np.abs(values)))
            clipping = float(np.mean((pcm == -32768) | (pcm == 32767)))
            duration = len(pcm) / audio.format.sample_rate
            eligible = (cfg.min_duration <= duration <= cfg.max_duration
                        and rms >= cfg.min_rms and clipping <= cfg.max_clipping)
            return SpeakerQualitySummary(eligible=eligible, reason="ok" if eligible else "invalid_audio",
                duration=duration, rms=rms, peak=peak, clipping=clipping, samples=len(pcm),
                channels=pcm.shape[1], sample_rate=audio.format.sample_rate)
        except Exception:
            return bad
