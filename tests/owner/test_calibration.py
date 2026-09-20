from uuid import UUID
import pytest
from app.owner.models import OwnerError, State


def test_complete_separated_calibration(calibrated):
    result = calibrated.calibration.status(calibrated.profile.profile_id)
    assert result["state"] == "calibrated"
    assert (result["owner_count"], result["nonowner_count"], result["holdout_count"]) == (8, 20, 4)
    assert result["replay"] == {"count": 3, "rejected": 3}
    assert calibrated.profile.calibration == "pending"  # No silent profile migration.
    record = calibrated.store.load(calibrated.profile.profile_id)
    assert len(record.private["digests"]) == 35
    assert record.private["acceptance"] >= .8
    assert record.private["acceptance"] - record.private["rejection"] >= .099999
    assert "digests" not in record.model_dump_json() + repr(record)


@pytest.mark.parametrize("consent", [False, None, "yes", 1])
def test_consent_required(harness, consent):
    with pytest.raises(OwnerError):
        harness.calibration.begin(harness.profile.profile_id, consent=consent)
    assert harness.capture_count == 0


def test_insufficient_and_invalid_transitions(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    for action in (lambda: harness.calibration.freeze(key), lambda: harness.calibration.approve(key, consent=True),
                   lambda: harness.calibration.collect(key, "holdout", "quiet", consent=True)):
        with pytest.raises(OwnerError):
            action()
    assert harness.capture_count == 0


def test_duplicate_sample_not_in_distribution(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.calibration.collect(key, "owner", "quiet", consent=True)
    harness.reuse = True
    with pytest.raises(OwnerError, match="duplicate_sample"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.calibration.status(key)["owner_count"] == 1


def test_rejected_phrase_does_not_affect_calibration(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.phrase_wrong = True
    with pytest.raises(OwnerError, match="phrase_mismatch"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.calibration.status(key)["owner_count"] == 0


def test_cancel_resume_preserves_completed_samples(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.calibration.collect(key, "owner", "quiet", consent=True)
    def cancel():
        raise OwnerError("cancelled")
    harness.before_capture = cancel
    with pytest.raises(OwnerError):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.calibration.status(key)["owner_count"] == 1


@pytest.mark.parametrize("change", ["model", "profile", "config"])
def test_mutation_invalidates_calibration(calibrated, change):
    key = calibrated.profile.profile_id
    if change == "model":
        calibrated.engine.identity = calibrated.identity.model_copy(update={"revision": "other"})
    elif change == "profile":
        calibrated.profile = calibrated.profile.model_copy(update={"enrollment_session": UUID(int=999)})
    else:
        calibrated.calibration.settings = calibrated.settings.model_copy(update={"speaker":
            calibrated.settings.speaker.model_copy(update={"min_rms": .01})})
    with pytest.raises(OwnerError):
        calibrated.calibration.current(key, calibrated=True)


@pytest.mark.parametrize("action", ["suspend", "revoke", "delete"])
def test_lifecycle_denies_pilot(calibrated, action):
    key = calibrated.profile.profile_id
    calibrated.calibration.change(key, action, consent=True)
    assert calibrated.pilot.run(key).status == "blocked"
    assert calibrated.capture_count == 0


def test_failed_update_preserves_calibration(calibrated):
    key = calibrated.profile.profile_id
    before = calibrated.store.load(key).document()
    calibrated.store.fail = True
    with pytest.raises(OwnerError):
        calibrated.calibration.change(key, "revoke", consent=True)
    assert calibrated.store.load(key).document() == before



def test_enrollment_audio_cannot_be_owner_sample(harness):
    from app.speaker.calibration import waveform_hash
    from uuid import uuid4
    audio = harness.capture("test", uuid4(), uuid4(), guard=lambda: None)
    harness.profile = harness.profile.model_copy(update={"enrollment_hashes": (waveform_hash(audio),)})
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.reuse = True
    with pytest.raises(OwnerError, match="duplicate_sample"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)


def test_holdout_cannot_reuse_development_buffer(calibrated):
    from copy import deepcopy
    key = calibrated.profile.profile_id
    record = calibrated.store.load(key)
    calibrated.store.records[key]["state"] = State.HOLDOUT.value
    # Last replay capture also belongs to this enrollment's evaluation ledger.
    calibrated.reuse = True
    with pytest.raises(OwnerError, match="duplicate_sample"):
        calibrated.calibration.collect(key, "holdout", "quiet", consent=True)


def test_contradictory_calibration_cannot_freeze(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    for i in range(8):
        harness.calibration.collect(key, "owner", "quiet" if i % 2 else "different_environment", consent=True)
    # Non-owner sounds as similar as the owner: no separating threshold exists.
    for i in range(20):
        harness.calibration.collect(key, "nonowner", "quiet" if i % 2 else "different_environment",
                                    consent=True, participant=UUID(int=10 + i % 3))
    assert harness.calibration.freeze(key)["state"] == "calibration_inconclusive"
    with pytest.raises(OwnerError):
        harness.calibration.approve(key, consent=True)


def test_insufficient_nonowners_cannot_freeze(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    for i in range(8):
        harness.calibration.collect(key, "owner", "quiet" if i % 2 else "different_environment", consent=True)
    harness.score = .2
    harness.calibration.collect(key, "nonowner", "quiet", consent=True, participant=UUID(int=10))
    with pytest.raises(OwnerError, match="insufficient_samples"):
        harness.calibration.freeze(key)


def test_holdout_failure_requires_new_calibration(calibrated):
    key = calibrated.profile.profile_id
    data = calibrated.store.records[key]
    data["state"] = State.REPLAY.value
    data["private"]["holdout"].update(accepted=3, rejected=1)
    assert calibrated.calibration.evaluate(key)["state"] == "calibration_inconclusive"
    with pytest.raises(OwnerError):
        calibrated.calibration.approve(key, consent=True)



def test_delete_uncalibrated_profile_requires_consent(harness):
    key = harness.profile.profile_id
    with pytest.raises(OwnerError):
        harness.calibration.change(key, "delete")
    assert harness.profile is not None
    assert harness.calibration.change(key, "delete", consent=True)["state"] == "deleted"
    assert harness.profile is None


def test_backend_exception_never_exposes_private_text(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    def failed(*args, **kwargs):
        raise ValueError("PRIVATE_MARKER")
    harness.calibration.capture = failed
    with pytest.raises(OwnerError) as error:
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert str(error.value) == "access_denied"
