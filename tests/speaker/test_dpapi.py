from types import SimpleNamespace
import pytest
from app.speaker.dpapi import DPAPIProtector
from app.speaker.contracts import SpeakerError
from app.speaker.private_store import private_root,provision_private_root,PrivateRecords
from uuid import uuid4
from tests.speaker.conftest import FakeProtector

def test_lazy_mock_roundtrip():
    calls=[]
    data={}
    def crypt(raw,decrypt=False):
        calls.append(decrypt)
        if decrypt:return data[raw]
        data[b"sealed"]=raw
        return b"sealed"
    p=DPAPIProtector(api_factory=lambda:SimpleNamespace(crypt_bytes=crypt))
    assert calls==[]
    assert p.unprotect(p.protect(b"synthetic"))==b"synthetic"
    assert calls==[False,True]

@pytest.mark.parametrize("value",[b"",None,"text",b"x"*131073],ids=["empty","none","text","oversized"])
def test_invalid(value):
    p=DPAPIProtector(api_factory=lambda:pytest.fail("must_not_load"))
    with pytest.raises(SpeakerError): p.protect(value)

@pytest.mark.parametrize("decrypt",[False,True])
def test_error_no_fallback(decrypt,capsys):
    def fail(*a,**kw):raise RuntimeError("PRIVATE_BYTES")
    p=DPAPIProtector(api_factory=lambda:SimpleNamespace(crypt_bytes=fail))
    with pytest.raises(SpeakerError,match="protection_failed") as e:
        (p.unprotect if decrypt else p.protect)(b"synthetic")
    assert "PRIVATE" not in str(e.value)+capsys.readouterr().out

def test_wrong_user_mock():
    p=DPAPIProtector(api_factory=lambda:SimpleNamespace(crypt_bytes=lambda *a,**kw:None))
    with pytest.raises(SpeakerError): p.unprotect(b"wrong-user")

def test_private_root_rejects_repo():
    from app.speaker.profiles import REPO
    with pytest.raises(SpeakerError): private_root(REPO/"profiles")

def test_no_synced_root(tmp_path):
    with pytest.raises(SpeakerError): private_root(tmp_path/"OneDrive"/"profiles")

def test_root_acl_before_records(tmp_path):
    called=[]
    root=tmp_path/"private"
    provision_private_root(root,api=SimpleNamespace(restrict_directory=lambda p:called.append(p)))
    assert called==[root] and not list(root.iterdir())

def test_private_records(tmp_path):
    store=PrivateRecords(tmp_path,FakeProtector())
    key=uuid4(); store.save(key,{"kind":"test"})
    assert store.load(key)=={"kind":"test"}
    with pytest.raises(SpeakerError): store.save(key,{"kind":"replacement"})
    assert store.load(key)=={"kind":"test"}
