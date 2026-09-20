from uuid import uuid4
import pytest
from app.owner.challenge import Challenges, PHRASES
from app.owner.models import Configuration, OwnerError, Challenge


def test_creation_expiry_and_single_use():
    now = [0.]
    service = Challenges(Configuration(), clock=lambda: now[0])
    session = uuid4()
    challenge = service.create(session)
    assert challenge.phrase in PHRASES and challenge.model_dump() == {}
    assert service.consume(challenge, session) == challenge.phrase
    with pytest.raises(OwnerError, match="challenge_replayed"):
        service.consume(challenge, session)
    expired = service.create(session)
    now[0] = 60
    with pytest.raises(OwnerError, match="challenge_expired"):
        service.consume(expired, session)


@pytest.mark.parametrize("fault", ["phrase", "session", "handle"])
def test_substitution_consumes_challenge(fault):
    service = Challenges(Configuration())
    session = uuid4()
    challenge = service.create(session)
    altered = challenge.model_copy(update={"phrase": "untrusted"}) if fault == "phrase" else challenge
    if fault == "handle":
        altered = Challenge(phrase=challenge.phrase)
    with pytest.raises(OwnerError):
        service.consume(altered, uuid4() if fault == "session" else session)


def test_stt_from_wrong_audio_never_accepted(harness):
    from types import SimpleNamespace
    harness.calibration.begin(harness.profile.profile_id, consent=True)
    harness.calibration.stt = SimpleNamespace(transcribe_audio=lambda *a, **k:
        SimpleNamespace(status="succeeded", audio_id=uuid4(), raw_transcript=PHRASES[0]))
    with pytest.raises(OwnerError, match="stt_rejected"):
        harness.calibration.collect(harness.profile.profile_id, "owner", "quiet", consent=True)


def test_expiry_during_stt_rejects(harness):
    harness.calibration.begin(harness.profile.profile_id, consent=True)
    harness.after_stt = lambda: setattr(harness, "now", 100.)
    with pytest.raises(OwnerError, match="challenge_expired"):
        harness.calibration.collect(harness.profile.profile_id, "owner", "quiet", consent=True)


def test_expiry_before_capture_prevents_audio(harness):
    harness.calibration.begin(harness.profile.profile_id, consent=True)
    harness.before_capture = lambda: setattr(harness, "now", 100.)
    with pytest.raises(OwnerError, match="challenge_expired"):
        harness.calibration.collect(harness.profile.profile_id, "owner", "quiet", consent=True)
    assert harness.capture_count == 0
