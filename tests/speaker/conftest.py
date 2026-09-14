import builtins
import socket
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import numpy as np
import pytest
from app.audio.models import AudioFormat, RecordedAudio
from app.speaker.models import ModelIdentity, SpeakerProfile, SpeakerConfiguration, ThresholdConfiguration
from app.speaker.quality import NumericalQuality
from app.speaker.thresholds import BoundedThresholdPolicy
from app.speaker.profiles import check_cancel
from app.speaker.contracts import SpeakerError

@pytest.fixture(autouse=True)
def no_integrations(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"sounddevice", "sherpa_onnx", "torch", "faster_whisper", "onnxruntime", "ctypes"}:
            raise AssertionError("forbidden_integration")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    def blocked(*a, **kw): raise AssertionError("forbidden_network")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)

@pytest.fixture
def configuration():
    return SpeakerConfiguration(embedding_dimension=3, min_duration=.1, max_duration=2)

@pytest.fixture
def identity():
    return ModelIdentity(name="synthetic", revision="v1", sha256="0"*64, preprocessing="pcm16-v1", dimension=3)

@pytest.fixture
def policy(identity):
    return BoundedThresholdPolicy(ThresholdConfiguration(version="synthetic-v1", model=identity,
        acceptance=.8, review=.5, calibration="synthetic"))

@pytest.fixture
def audio():
    def make():
        wave = (np.sin(np.arange(16000)*2*np.pi*220/16000)*4000).astype(np.int16)
        return RecordedAudio(format=AudioFormat(), samples=wave[:, None])
    return make

@pytest.fixture
def profile(identity):
    now = datetime(2026,1,1,tzinfo=timezone.utc)
    return SpeakerProfile(profile_id=UUID(int=1), model=identity, template=[1.,0.,0.],
        sample_count=3, created_at=now, updated_at=now, policy_version="synthetic-v1", calibration="synthetic")

class MemoryStore:
    def __init__(self, profile=None):
        self.values = {} if profile is None else {profile.profile_id:profile}
    def load(self, key):
        if key not in self.values: raise SpeakerError("invalid_profile")
        return self.values[key]
    def save(self, profile, *, cancel=None):
        check_cancel(cancel)
        self.values[profile.profile_id] = profile
    def delete(self, key): self.values.pop(key, None)
    def list_ids(self): return tuple(self.values)

class FakeProtector:
    """Opaque random tokens backed by test memory; NOT encryption."""
    def __init__(self):
        self.values = {}
    def protect(self, plaintext):
        token = uuid4().bytes
        self.values[token] = plaintext
        return token
    def unprotect(self, token):
        if token not in self.values: raise SpeakerError("invalid_profile")
        return self.values[token]

@pytest.fixture
def engine(identity):
    return SimpleNamespace(identity=identity, extract=lambda audio, **kw: np.array([1.,0.,0.]))

@pytest.fixture
def quality(configuration):
    return NumericalQuality(configuration)
