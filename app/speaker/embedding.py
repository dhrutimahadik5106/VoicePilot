"""Numerical primitives, no model loader or network."""
import numpy as np
from app.speaker.contracts import SpeakerError

def normalized(value, dimension):
    try:
        vector = np.asarray(value, dtype=np.float64)
        if vector.shape != (dimension,) or not np.isfinite(vector).all():
            raise ValueError()
        scale = np.max(np.abs(vector))
        if scale <= 0:
            raise ValueError()
        vector = vector / scale
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 0:
            raise ValueError()
        # Immutable bytes prevent callers from re-enabling write access.
        return np.frombuffer((vector / norm).tobytes(), dtype=np.float64)
    except Exception:
        raise SpeakerError("invalid_embedding") from None

def cosine(left, right, dimension):
    return float(np.clip(np.dot(normalized(left, dimension), normalized(right, dimension)), -1, 1))

class UnavailableEmbeddingEngine:
    identity = None
    def extract(self, audio, *, cancel=None):
        raise SpeakerError("unavailable")
