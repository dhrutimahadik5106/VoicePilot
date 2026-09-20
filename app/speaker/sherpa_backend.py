"""Lazy CPU WeSpeaker adapter. No capture, persistence or fallback embeddings."""
import numpy as np
from app.core import timing
from app.speaker.artifacts import IDENTITY, fingerprint
from app.speaker.contracts import SpeakerError
from app.speaker.embedding import normalized
from app.speaker.profiles import check_cancel
from app.speaker.quality import NumericalQuality
from app.stt.audio_preprocessing import prepare_audio

def load_extractor(path):
    fingerprint(path)  # Only the pinned publisher graph may reach native parsing.
    try:
        import sherpa_onnx
        if sherpa_onnx.__version__ != "1.13.8":
            raise ImportError()
    except ImportError:
        raise SpeakerError("runtime_unavailable") from None
    try:
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(path), num_threads=1, debug=False, provider="cpu")
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        if extractor.dim != 256:
            raise ValueError()
        return extractor
    except Exception:
        raise SpeakerError("model_invalid") from None

class SherpaEmbeddingEngine:
    identity = IDENTITY
    def __init__(self, path, configuration, *, factory=load_extractor, inspector=fingerprint):
        self.path, self.configuration = path, configuration
        self.factory, self.inspector = factory, inspector
        self._extractor = None

    def ready(self):
        if self.configuration.embedding_dimension != self.identity.dimension:
            raise SpeakerError("model_invalid")
        with timing.span("speaker_integrity"):
            self.inspector(self.path)
        if self._extractor is None:
            with timing.span("speaker_model_load", "cold"):
                self._extractor = self.factory(self.path)
        if self._extractor.dim != self.identity.dimension:
            self._extractor = None
            raise SpeakerError("model_invalid")

    def extract(self, audio, *, cancel=None):
        check_cancel(cancel)
        if not NumericalQuality(self.configuration).assess(audio).eligible:
            raise SpeakerError("invalid_audio")
        try:
            # Quality requires 16 kHz; no resampling or decoder import is necessary.
            samples = prepare_audio(audio, decoder=None, max_duration=self.configuration.max_duration)
            if samples.dtype != np.float32 or samples.ndim != 1 or not samples.flags.c_contiguous or not np.isfinite(samples).all():
                raise SpeakerError("invalid_audio")
            check_cancel(cancel)
            temperature = "cold" if self._extractor is None else "warm"
            self.ready()
            stream = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=16000, waveform=samples)
            stream.input_finished()
            if not self._extractor.is_ready(stream):
                raise SpeakerError("invalid_audio")
            check_cancel(cancel)
            with timing.span("speaker_inference", temperature):
                vector = self._extractor.compute(stream)
            check_cancel(cancel)
            return normalized(vector, self.identity.dimension)
        except SpeakerError:
            raise
        except Exception:
            raise SpeakerError("inference_failed") from None
