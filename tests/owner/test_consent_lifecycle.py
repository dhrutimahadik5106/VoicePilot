"""Fake clocks and synthetic records only; consent never spends challenge lifetime."""
from copy import deepcopy
from threading import Event
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.owner.cli import main, PRIVACY
from app.owner.models import Configuration, OwnerError, TrialConsent
from app.owner.challenge import Challenges


PARTICIPANT = UUID(int=123)


def prepare(h, group):
    key = h.profile.profile_id
    if group == "voice-pilot":
        h.calibrate()
        return
    h.calibration.begin(key, consent=True)
    if group == "owner":
        return
    for i in range(8):
        h.calibration.collect(key, "owner", "quiet" if i % 2 else "different_environment", consent=True)
    if group == "nonowner":
        return
    h.score = .2
    for i in range(20):
        h.calibration.collect(key, "nonowner", "quiet" if i % 2 else "different_environment",
                              consent=True, participant=UUID(int=10 + i % 3))
    h.calibration.freeze(key)
    h.score = .95
    if group == "replay":
        for i in range(4):
            h.calibration.collect(key, "holdout", "quiet" if i % 2 else "different_environment", consent=True)


def arguments(h, group):
    args = [group, "--profile", str(h.profile.profile_id)]
    if group != "voice-pilot":
        args += ["--environment", "quiet"]
    if group == "nonowner":
        args += ["--participant", str(PARTICIPANT)]
    return args


@pytest.mark.parametrize("group", ["owner", "nonowner", "holdout", "replay", "voice-pilot"])
def test_slow_privacy_and_all_consents_precede_fresh_challenge(harness, monkeypatch, group):
    h = harness
    prepare(h, group)
    h.capture_count = h.stt_calls = 0
    events = []
    original = h.challenges.create

    def create(session, **kwargs):
        assert events == (["privacy", "operator", "participant"] if group == "nonowner"
                          else ["privacy", "operator"])
        events.append("create")
        return original(session, **kwargs)

    def write(message):
        if message == PRIVACY:
            assert not h.challenges.pending
            h.now += 300  # Deliberate privacy reading takes much longer than the TTL.
            events.append("privacy")

    def read(prompt):
        assert not h.challenges.pending and h.capture_count == 0
        h.now += 300
        if "I CONSENT TO THIS TRIAL" in prompt:
            events.append("participant")
            return "I CONSENT TO THIS TRIAL"
        events.append("operator")
        return "CONSENT " + group.upper()

    def present(phrase):
        assert events[-1] == "create" and not h.challenges.pending
        h.now += 300  # Slow output must not consume the post-display window.
        events.append("displayed")

    def before_capture():
        if h.capture_count == 0:
            assert events[-1] == "displayed"
            row, = h.challenges.pending.values()
            assert row[2] - h.now == h.settings.owner.challenge_expiry == 45

    monkeypatch.setattr(h.challenges, "create", create)
    h.calibration.present = present
    h.before_capture = before_capture
    runtime = SimpleNamespace(calibration=lambda: h.calibration, pilot=lambda _: h.pilot)
    assert main(arguments(h, group), settings=h.settings, factory=lambda *a, **k: runtime,
                read=read, write=write, interactive=lambda: True) == 0
    assert h.capture_count == (2 if group == "voice-pilot" else 1)
    assert not h.challenges.pending
    if group != "voice-pilot":
        assert h.backend.mutations == h.launch_backend.launched == 0


@pytest.mark.parametrize("stage", ["before_consent", "participant_consent", "after_consent", "display"])
def test_cancellation_keeps_eight_owner_samples_and_no_trial(harness, stage):
    h = harness
    prepare(h, "nonowner")
    h.capture_count = h.stt_calls = 0
    before = h.store.load(h.profile.profile_id).document()
    cancelled = Event()
    h.calibration.cancel = cancelled

    def read(prompt):
        if stage == "before_consent":
            raise KeyboardInterrupt()
        if "I CONSENT TO THIS TRIAL" in prompt:
            if stage == "participant_consent":
                return "cancel"
            if stage == "after_consent":
                cancelled.set()
            return "I CONSENT TO THIS TRIAL"
        return "CONSENT NONOWNER"

    def present(phrase):
        assert stage == "display"
        cancelled.set()

    h.calibration.present = present
    runtime = SimpleNamespace(calibration=lambda: h.calibration)
    assert main(arguments(h, "nonowner"), settings=h.settings, factory=lambda *a, **k: runtime,
                read=read, write=lambda _: None, interactive=lambda: True) == 2
    assert h.capture_count == h.stt_calls == 0 and not h.challenges.pending
    assert h.store.load(h.profile.profile_id).document() == before
    assert before["private"]["owner"]["count"] == 8
    assert before["private"]["nonowner"]["count"] == 0
    assert h.backend.mutations == h.launch_backend.launched == 0


@pytest.mark.parametrize("field,value", [("participant", UUID(int=124)),
    ("profile_id", UUID(int=125)), ("environment", "different_environment"), ("group", "owner")])
def test_selected_trial_substitution_rejected_before_capture(harness, field, value):
    h = harness
    prepare(h, "nonowner")
    h.capture_count = 0
    before = h.store.load(h.profile.profile_id).document()
    values = dict(profile_id=h.profile.profile_id, group="nonowner", environment="quiet", participant=PARTICIPANT)
    consent = TrialConsent(**values)
    values[field] = value
    with pytest.raises(OwnerError, match="binding_mismatch"):
        h.calibration.collect(**values, consent=consent)
    assert h.capture_count == 0 and not h.challenges.pending
    assert h.store.load(h.profile.profile_id).document() == before
    assert consent.model_dump() == {} and str(PARTICIPANT) not in repr(consent)


def test_display_completes_before_clock_starts_and_challenge_is_single_use():
    now = [0.]
    challenges = Challenges(Configuration(), clock=lambda: now[0])
    session = uuid4()
    def present(phrase):
        assert not challenges.pending
        now[0] = 300.
    challenge = challenges.create(session, present=present)
    assert challenges.pending[challenge.handle][2] == 345.
    assert challenges.consume(challenge, session) == challenge.phrase
    with pytest.raises(OwnerError, match="challenge_replayed"):
        challenges.consume(challenge, session)


@pytest.mark.parametrize("delay_at", ["enter", "notice", "constructor"])
def test_expiry_before_microphone_preserves_record(harness, monkeypatch, delay_at):
    from app.owner.runtime import Runtime
    import app.audio.recorder as recorder_module

    h = harness
    prepare(h, "nonowner")
    before = deepcopy(h.store.load(h.profile.profile_id).document())
    calls = []
    def read(prompt):
        if delay_at == "enter":
            h.now += 45
        return ""
    def write(message):
        if delay_at == "notice" and message.startswith("Recording;"):
            h.now += 45
    class Recorder:
        def __init__(self, settings):
            if delay_at == "constructor":
                h.now += 45
        def record(self, *args, **kwargs):
            calls.append("microphone")
            raise AssertionError("expired_capture")

    monkeypatch.setattr(recorder_module, "SoundDeviceRecorder", Recorder)
    runtime = Runtime(h.settings, read=read, write=write)
    h.calibration.capture = runtime.capture
    h.calibration.present = runtime.present_challenge
    with pytest.raises(OwnerError, match="challenge_expired"):
        h.calibration.collect(h.profile.profile_id, "nonowner", "quiet", consent=True, participant=PARTICIPANT)
    assert calls == [] and not h.challenges.pending
    assert h.store.load(h.profile.profile_id).document() == before
    assert h.calibration.status(h.profile.profile_id)["nonowner_count"] == 0


def test_runtime_wires_display_before_deadline_without_private_repository(harness, monkeypatch):
    from app.owner.runtime import Runtime
    runtime = Runtime(harness.settings, write=lambda _: None)
    monkeypatch.setattr(runtime.local, "repository", lambda: harness.repository)
    calibration = runtime.calibration()
    assert calibration.present == runtime.present_challenge
    assert calibration.capture == runtime.capture
