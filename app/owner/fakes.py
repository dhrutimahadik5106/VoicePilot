"""Synthetic development harness. No profiles, models, devices or Windows API access."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID
import numpy as np
from app.audio.models import AudioFormat, RecordedAudio
from app.core.config import Settings
from app.speaker.models import ModelIdentity, SpeakerProfile
from app.owner.models import Configuration, OwnerError, Record
from app.owner.calibration import Calibration
from app.owner.challenge import Challenges, PHRASES
from app.owner.pilot import Pilot
from app.operations.controller import Controller
from app.operations.fakes import FakeBackend, FakeStore
from app.operations.models import Configuration as OperationsConfiguration
from app.launch.models import Configuration as LaunchConfiguration, Discovery, Status, ProcessObservation
from app.launch.controller import LaunchController
from app.execution.cancellation import CancellationHub
from contextlib import contextmanager


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.fail = False

    def load(self, key):
        if key not in self.records:
            raise OwnerError("calibration_required")
        return Record.model_validate(deepcopy(self.records[key]))

    def save(self, key, record, *, previous=None):
        if self.fail:
            raise OwnerError("storage_failed")
        if previous is not None and self.records[key]["private"]["revision"] != previous:
            raise OwnerError("concurrent_update")
        self.records[key] = deepcopy(record.document())

    def delete(self, key):
        self.records.pop(key, None)


class LaunchBackend:
    fake = True

    def __init__(self):
        self.launched = 0

    def discover(self, application, timeout):
        return Discovery(application_id=application, status=Status.AVAILABLE, identity="a" * 64)

    def observe(self, application, identity, timeout):
        return ProcessObservation(application_id=application, identity=identity, matched=bool(self.launched))

    @contextmanager
    def revalidate(self, application, identity, timeout):
        yield object()

    def launch(self, image, *, guard):
        guard()
        self.launched += 1


class Harness:
    def __init__(self):
        self.settings = Settings(owner=Configuration(calibration_enabled=True, pilot_enabled=True),
            speaker_verification_enabled=True, operations=OperationsConfiguration(enabled=True),
            launch=LaunchConfiguration(real_execution_enabled=True))
        self.identity = ModelIdentity(name="synthetic", revision="v1", sha256="0" * 64,
                                      preprocessing="synthetic-v1", dimension=3)
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.profile = SpeakerProfile(profile_id=UUID(int=1), model=self.identity, template=[1., 0., 0.],
            sample_count=3, enrollment_session=UUID(int=2), enrollment_hashes=("a" * 64,) * 3,
            created_at=timestamp, updated_at=timestamp, policy_version="calibration-pending")
        self.now = 0.
        self.counter = 0
        self.phrase_counter = 0
        self.score = .95
        self.command_score = .95
        self.command = "increase volume"
        self.phrase_wrong = False
        self.audio_text = {}
        self.audio_scores = {}
        self.capture_count = 0
        self.stt_calls = 0
        self.before_capture = lambda: None
        self.after_stt = lambda: None
        self.last_audio = None
        self.reuse = False
        self.store = MemoryStore()
        self.repository = SimpleNamespace(load=lambda key: self.profile, delete=self.delete_profile)
        self.engine = SimpleNamespace(identity=self.identity, extract=self.extract)
        self.challenges = Challenges(self.settings.owner, clock=lambda: self.now, choose=self.choose)
        self.calibration = Calibration(self.settings, self.repository, self.store, self.engine, self,
            self.capture, challenges=self.challenges)
        self.backend = FakeBackend()
        self.launch_backend = LaunchBackend()
        self.hub = CancellationHub()
        self.pilot = Pilot(self.calibration,
            Controller(self.settings.operations, backend=self.backend, store=FakeStore(), hub=self.hub),
            LaunchController(self.settings.launch, backend=self.launch_backend), clock=lambda: self.now, hub=self.hub)

    def delete_profile(self, key):
        self.profile = None

    def choose(self, phrases):
        phrase = phrases[self.phrase_counter % len(phrases)]
        self.phrase_counter += 1
        return phrase

    def capture(self, phrase, session, audio_id, *, guard):
        self.before_capture()
        guard()
        self.capture_count += 1
        if self.reuse:
            return self.last_audio
        self.counter += 1
        pcm = (np.sin(np.arange(64000) * 2 * np.pi * (200 + self.counter) / 16000) * 4000).astype(np.int16)
        audio = RecordedAudio(format=AudioFormat(), samples=pcm[:, None])
        self.audio_text[id(audio)] = "unrelated private marker" if self.phrase_wrong and phrase else phrase or self.command
        self.audio_scores[id(audio)] = self.score if phrase else self.command_score
        self.last_audio = audio
        return audio

    def extract(self, audio, **kwargs):
        score = self.audio_scores[id(audio)]
        return [score, (1-score**2)**.5, 0.]

    def transcribe_audio(self, audio, *, audio_id, cancel=None):
        self.stt_calls += 1
        text = self.audio_text[id(audio)]
        self.after_stt()
        return SimpleNamespace(status="succeeded", audio_id=audio_id, raw_transcript=text, normalized_transcript=text)

    def calibrate(self):
        key = self.profile.profile_id
        self.calibration.begin(key, consent=True)
        for i in range(8):
            self.calibration.collect(key, "owner", "quiet" if i % 2 else "different_environment", consent=True)
        self.score = .2
        for i in range(20):
            self.calibration.collect(key, "nonowner", "quiet" if i % 2 else "different_environment",
                consent=True, participant=UUID(int=10 + i % 3))
        self.calibration.freeze(key)
        self.score = .95
        for i in range(4):
            self.calibration.collect(key, "holdout", "quiet" if i % 2 else "different_environment", consent=True)
        for _ in range(3):
            self.calibration.collect(key, "replay", "quiet", consent=True)
        self.calibration.evaluate(key)
        self.calibration.approve(key, consent=True)
        self.capture_count = self.stt_calls = 0
        return self
