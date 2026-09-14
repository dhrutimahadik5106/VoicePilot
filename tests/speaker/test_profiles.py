import os
from threading import Event
from uuid import uuid4
import pytest
from app.speaker.profiles import ProtectedProfileRepository
from app.speaker.protection import UnavailableBiometricProtector
from app.speaker.contracts import SpeakerError
from tests.speaker.conftest import FakeProtector

def test_roundtrip_and_delete(tmp_path,profile):
    protector=FakeProtector()
    repo=ProtectedProfileRepository(tmp_path,protector)
    repo.save(profile)
    assert repo.load(profile.profile_id).model==profile.model
    assert repo.list_ids()==(profile.profile_id,)
    payload=next(tmp_path.iterdir()).read_bytes()
    assert b"template" not in payload
    repo.delete(profile.profile_id)
    assert repo.list_ids()==()

def test_unavailable_no_plaintext(tmp_path,profile):
    repo=ProtectedProfileRepository(tmp_path,UnavailableBiometricProtector())
    with pytest.raises(SpeakerError,match="unavailable"): repo.save(profile)
    assert list(tmp_path.iterdir())==[]

@pytest.mark.parametrize("identifier",["../escape","a/b","CON",str(uuid4()),None])
def test_traversal(tmp_path,identifier):
    repo=ProtectedProfileRepository(tmp_path,FakeProtector())
    with pytest.raises(SpeakerError): repo.load(identifier)

def test_failed_replace_preserves_old(tmp_path,profile,monkeypatch):
    repo=ProtectedProfileRepository(tmp_path,FakeProtector())
    repo.save(profile)
    before=next(tmp_path.iterdir()).read_bytes()
    def fail(*a): raise OSError("PRIVATE_PATH")
    monkeypatch.setattr(os,"replace",fail)
    with pytest.raises(SpeakerError,match="^unavailable$"):
        repo.save(profile)
    assert len(list(tmp_path.iterdir()))==1
    assert next(tmp_path.iterdir()).read_bytes()==before

def test_cancel_before_commit(tmp_path,profile):
    event=Event()
    protector=FakeProtector()
    repo=ProtectedProfileRepository(tmp_path,protector)
    repo.save(profile)
    before=next(tmp_path.iterdir()).read_bytes()
    original=protector.protect
    def protect(value):
        event.set()
        return original(value)
    protector.protect=protect
    with pytest.raises(SpeakerError,match="cancelled"): repo.save(profile,cancel=event)
    assert next(tmp_path.iterdir()).read_bytes()==before

@pytest.mark.parametrize("case",["corrupt","large","schema","dimension","wrong_id"])
def test_corrupt(tmp_path,profile,case):
    import json
    protector=FakeProtector()
    repo=ProtectedProfileRepository(tmp_path,protector)
    repo.save(profile)
    path=next(tmp_path.iterdir())
    if case=="corrupt": path.write_bytes(b"not-protected")
    elif case=="large": path.write_bytes(b"x"*131073)
    else:
        document=json.loads(protector.unprotect(path.read_bytes()))
        if case=="schema": document["schema_version"]=2
        if case=="dimension": document["template"]=[1,0]
        if case=="wrong_id": document["profile_id"]=str(uuid4())
        path.write_bytes(protector.protect(json.dumps(document).encode()))
    with pytest.raises(SpeakerError): repo.load(profile.profile_id)

def test_missing_root_not_created(tmp_path,profile):
    root=tmp_path/"absent"
    repo=ProtectedProfileRepository(root,FakeProtector())
    with pytest.raises(SpeakerError): repo.save(profile)
    assert not root.exists()

def test_repository_root_rejected(profile):
    from app.speaker.profiles import REPO
    repo=ProtectedProfileRepository(REPO,FakeProtector())
    with pytest.raises(SpeakerError): repo.save(profile)

def test_symlink_policy(tmp_path,profile,monkeypatch):
    from pathlib import Path
    repo=ProtectedProfileRepository(tmp_path,FakeProtector())
    original=Path.is_symlink
    monkeypatch.setattr(Path,"is_symlink",lambda p: True if p==tmp_path else original(p))
    with pytest.raises(SpeakerError): repo.save(profile)

def test_unprotect_failure(tmp_path,profile):
    protector=FakeProtector()
    repo=ProtectedProfileRepository(tmp_path,protector)
    repo.save(profile)
    repo.protector=UnavailableBiometricProtector()
    with pytest.raises(SpeakerError,match="unavailable"): repo.load(profile.profile_id)

def test_protector_error_does_not_leak(tmp_path,profile,capsys,caplog):
    protector=FakeProtector()
    def fail(data): raise RuntimeError("PRIVATE_BIOMETRIC_PAYLOAD")
    protector.protect=fail
    with pytest.raises(SpeakerError,match="^unavailable$") as error:
        ProtectedProfileRepository(tmp_path,protector).save(profile)
    assert "PRIVATE" not in repr(error.value)+capsys.readouterr().out+caplog.text
    assert not list(tmp_path.iterdir())

def test_junction_policy(tmp_path,profile,monkeypatch):
    from pathlib import Path
    repo=ProtectedProfileRepository(tmp_path,FakeProtector())
    original=Path.is_junction
    monkeypatch.setattr(Path,"is_junction",lambda p: True if p==tmp_path else original(p))
    with pytest.raises(SpeakerError): repo.save(profile)
