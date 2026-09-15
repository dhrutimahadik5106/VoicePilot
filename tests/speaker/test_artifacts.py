import hashlib
import io
from pathlib import Path
import pytest
from app.speaker import artifacts as a
from app.speaker.contracts import SpeakerError

def test_missing(tmp_path):
    with pytest.raises(SpeakerError,match="model_missing"): a.fingerprint(tmp_path/"absent.onnx")

@pytest.mark.parametrize("data",[b"",b"not an onnx model"])
def test_invalid(tmp_path,data):
    p=tmp_path/"bad.onnx"; p.write_bytes(data)
    with pytest.raises(SpeakerError,match="model_invalid"): a.fingerprint(p)

def fixture_hash(monkeypatch):
    original=a.fingerprint
    monkeypatch.setattr(a,"fingerprint",lambda p: original(p,expected=hashlib.sha256(b"fake-model").hexdigest()))

def test_provision_atomic(tmp_path,monkeypatch):
    fixture_hash(monkeypatch)
    p=tmp_path/"model.onnx"
    calls=[]
    report=a.provision(p,opener=lambda:io.BytesIO(b"fake-model"),validator=lambda p:calls.append(p))
    assert report["status"]=="provisioned" and calls and p.read_bytes()==b"fake-model"
    assert p.with_suffix(".speaker-model.json").exists()
    assert not list(tmp_path.glob(".partial-*"))

def test_no_replace(tmp_path):
    p=tmp_path/"model.onnx"; p.write_bytes(b"existing")
    with pytest.raises(SpeakerError): a.provision(p,opener=lambda:pytest.fail("network"))
    assert p.read_bytes()==b"existing"

def test_bad_checksum_rollback(tmp_path):
    p=tmp_path/"model.onnx"
    with pytest.raises(SpeakerError): a.provision(p,opener=lambda:io.BytesIO(b"bad"),validator=lambda _:None)
    assert not list(tmp_path.iterdir())

def test_parse_failure_rollback(tmp_path,monkeypatch):
    fixture_hash(monkeypatch)
    def fail(_): raise ValueError("PRIVATE_PATH")
    with pytest.raises(SpeakerError,match="provisioning_failed"):
        a.provision(tmp_path/"model.onnx",opener=lambda:io.BytesIO(b"fake-model"),validator=fail)
    assert not list(tmp_path.iterdir())

def test_oversize(tmp_path,monkeypatch):
    monkeypatch.setattr(a,"MAX_BYTES",4)
    with pytest.raises(SpeakerError): a.provision(tmp_path/"model.onnx",opener=lambda:io.BytesIO(b"12345"))
    assert not list(tmp_path.iterdir())

def test_reparse(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,"is_junction",lambda _:True)
    with pytest.raises(SpeakerError): a.safe_model_path(tmp_path/"model.onnx")
