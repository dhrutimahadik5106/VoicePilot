"""Pinned official model provisioning, invoked only by an explicit command."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from app.speaker.contracts import SpeakerError
from app.speaker.models import ModelIdentity

FILENAME = "wespeaker_en_voxceleb_resnet34.onnx"
SOURCE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + FILENAME
CHECKSUM_SOURCE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/checksum.txt"
SHA256 = "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94"
LICENSE = "CC-BY-4.0"
MAX_BYTES = 32_000_000
DEFAULT_PATH = Path("models/speaker") / FILENAME
IDENTITY = ModelIdentity(name="wespeaker-resnet34", revision="publisher-20241014",
    sha256=SHA256, preprocessing="pcm16-mono-sherpa-1-13-8", dimension=256)

def safe_model_path(path):
    path = Path(path).absolute()
    if path.suffix != ".onnx":
        raise SpeakerError("model_invalid")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise SpeakerError("model_invalid")
    return path

def fingerprint(path, *, expected=SHA256):
    try:
        path = safe_model_path(path)
        digest, count = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024*1024):
                count += len(chunk)
                if count > MAX_BYTES:
                    raise ValueError()
                digest.update(chunk)
        if count == 0 or digest.hexdigest() != expected:
            raise ValueError()
        return count
    except FileNotFoundError:
        raise SpeakerError("model_missing") from None
    except SpeakerError:
        raise
    except Exception:
        raise SpeakerError("model_invalid") from None

def inspect_model(path):
    size = fingerprint(path)
    return {"model_id":IDENTITY.name, "filename":FILENAME, "bytes":size, "source":SOURCE,
            "license":LICENSE, "dimension":256, "sample_rate":16000,
            "checksum_type":"publisher-sha256", "sha256":SHA256}

def official_stream():
    from urllib.request import urlopen
    from urllib.parse import urlparse
    stream = urlopen(SOURCE, timeout=30)
    final = urlparse(stream.geturl())
    if final.scheme != "https" or final.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
        stream.close()
        raise SpeakerError("model_invalid")
    return stream

def provision(path, *, opener=official_stream, validator=None):
    """Tests inject a stream and validator; production URL/hash are not CLI-overridable."""
    partial = None
    try:
        path = safe_model_path(path)
        if path.exists():
            result = inspect_model(path)  # Never replace an existing different model.
            return result | {"status":"already_provisioned"}
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_model_path(path)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".onnx", prefix=".partial-", delete=False) as output:
            partial = Path(output.name)
            total = 0
            with opener() as source:
                while chunk := source.read(1024*1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise SpeakerError("model_invalid")
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        fingerprint(partial)
        if validator is None:
            from app.speaker.sherpa_backend import load_extractor
            validator = load_extractor
        validator(partial)  # ONNX parse + expected dimension before activation.
        safe_model_path(path)
        if path.exists():
            raise SpeakerError("model_invalid")
        # Windows rename refuses overwrite; avoid replacing a concurrent provisioning result.
        os.rename(partial, path)
        partial = None
        metadata = inspect_model(path) | {"retrieved_at":datetime.now(timezone.utc).isoformat()}
        meta = path.with_suffix(".speaker-model.json")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                prefix=".metadata-", suffix=".tmp", delete=False) as output:
            partial = Path(output.name)
            json.dump(metadata, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, meta)
        partial = None
        return metadata | {"status":"provisioned"}
    except SpeakerError:
        raise
    except Exception:
        raise SpeakerError("provisioning_failed") from None
    finally:
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass  # Never expose private paths in cleanup errors.
