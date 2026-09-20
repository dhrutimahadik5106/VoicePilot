import json
from uuid import uuid4
import numpy as np
import pytest
from app.owner.storage import Store
from app.owner.models import OwnerError, Record
from app.owner.quality import check_audio
from app.audio.models import AudioFormat, RecordedAudio
from tests.speaker.conftest import FakeProtector


def record(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    return key, harness.store.load(key)


def test_encrypted_store_roundtrip_no_private_plaintext(harness, tmp_path):
    key, value = record(harness)
    protector = FakeProtector()
    store = Store(tmp_path, protector=protector, provisioner=lambda root: None)
    store.save(key, value)
    assert store.load(key).document() == value.document()
    assert b"provenance" not in store.path(key).read_bytes()
    assert "provenance" not in repr(value) + value.model_dump_json()
    payload = json.loads(next(iter(protector.values.values())))
    assert "template" not in payload["private"] and "transcript" not in str(payload)
    assert "embedding" not in str(payload)


def test_corrupt_store_safe_error(harness, tmp_path):
    key, value = record(harness)
    store = Store(tmp_path, protector=FakeProtector(), provisioner=lambda root: None)
    store.save(key, value)
    store.path(key).write_bytes(b"PRIVATE_MARKER")
    with pytest.raises(OwnerError) as error:
        store.load(key)
    assert str(error.value) == "profile_corrupt"


def test_atomic_failure_preserves_old_record(harness, tmp_path, monkeypatch):
    import os
    key, value = record(harness)
    store = Store(tmp_path, protector=FakeProtector(), provisioner=lambda root: None)
    store.save(key, value)
    before = store.path(key).read_bytes()
    def failed(*args):
        raise OSError("PRIVATE_MARKER")
    monkeypatch.setattr(os, "replace", failed)
    data = dict(value.private, revision=str(uuid4()))
    with pytest.raises(OwnerError, match="storage_failed"):
        store.save(key, Record(private=data), previous=value.private["revision"])
    assert store.path(key).read_bytes() == before
    assert not list(tmp_path.glob(".owner-*.tmp"))


@pytest.mark.parametrize("fault", ["count", "extra", "duplicate", "nan"])
def test_malformed_private_document_safe(harness, fault):
    key, value = record(harness)
    data = value.document()
    if fault == "count":
        data["private"]["owner"]["count"] = -1
    elif fault == "extra":
        data["private"]["transcript"] = "PRIVATE_MARKER"
    elif fault == "duplicate":
        data["private"]["digests"] = ["a" * 64, "a" * 64]
    else:
        data["private"]["owner"]["sum"] = float("nan")
    with pytest.raises(OwnerError) as error:
        Record.model_validate(data)
    assert "PRIVATE_MARKER" not in repr(error.value)


@pytest.mark.parametrize("fault", ["silence", "clipped", "short", "stereo", "rate", "mostly_silence"])
def test_quality_gates(harness, fault):
    pcm = (np.sin(np.arange(64000) * .1) * 4000).astype(np.int16)[:, None]
    rate = 16000
    if fault == "silence": pcm[:] = 0
    if fault == "clipped": pcm[:] = 32767
    if fault == "short": pcm = pcm[:16000]
    if fault == "stereo": pcm = np.repeat(pcm, 2, axis=1)
    if fault == "rate": rate = 8000
    if fault == "mostly_silence": pcm[16000:] = 0
    audio = RecordedAudio(format=AudioFormat(sample_rate=rate, channels=pcm.shape[1]), samples=pcm)
    with pytest.raises(OwnerError, match="capture_quality_failed"):
        check_audio(audio, harness.settings.speaker, harness.settings.owner)


@pytest.mark.parametrize("vector", [[float("nan"), 0., 1.], [1., 0.], [0., 0., 0.]])
def test_invalid_embedding_never_changes_calibration(harness, vector):
    from app.speaker.contracts import SpeakerError
    key, value = record(harness)
    harness.engine.extract = lambda *a, **k: vector
    with pytest.raises(OwnerError, match="capture_quality_failed"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.calibration.status(key)["owner_count"] == 0
