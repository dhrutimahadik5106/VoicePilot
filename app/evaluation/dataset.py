"""Explicit approved roots; validate annotations without opening any audio."""
from pathlib import Path
from app.evaluation.metrics import normalized

from app.evaluation.models import Manifest


class EvaluationError(ValueError):
    pass


def private_path(root, path):
    try:
        base = Path(root).resolve(strict=True)
        if not base.is_dir():
            raise ValueError()
        selected = Path(path)
        selected = selected if selected.is_absolute() else base / selected
        resolved = selected.resolve(strict=True)
        if not resolved.is_relative_to(base) or not resolved.is_file():
            raise ValueError()
        # No private input within the repo except the explicitly ignored subtree.
        repo = Path(__file__).resolve().parents[2]
        if resolved.is_relative_to(repo) and not resolved.is_relative_to(repo / "data/stt/private"):
            raise ValueError()
        return resolved
    except Exception:
        raise EvaluationError("invalid_private_path") from None


def validate_manifest(manifest, *, root=None, public_vocabulary=None):
    try:
        maps = {key: {} for key in ("speaker", "session", "recording_group", "audio_sha256", "audio")}
        ids = set()
        resolved_audio_splits = {}
        for row in manifest.rows:
            if row.recording_id in ids:
                raise ValueError()
            ids.add(row.recording_id)
            for key, assignments in maps.items():
                value = getattr(row, key)
                if value is not None and value in assignments and assignments[value] != row.split:
                    raise ValueError()
                assignments[value] = row.split
            if row.source_type == "consented_recording":
                if root is None:
                    raise ValueError()
                from datetime import date
                if date.fromisoformat(row.retention_review_date) < date.today():
                    raise ValueError()
                selected = private_path(root, row.audio)
                key = str(selected)
                if key in resolved_audio_splits and resolved_audio_splits[key] != row.split:
                    raise ValueError()
                resolved_audio_splits[key] = row.split
                if selected.suffix.lower() != ".wav":
                    raise ValueError()
            if public_vocabulary is not None:
                reference = normalized(row.ground_truth)
                if len(reference.split()) >= 2:
                    for entry in public_vocabulary.entries:
                        for form in entry.forms:
                            hint = normalized(form.text)
                            if reference == hint or reference in hint:
                                raise ValueError()
        return manifest
    except Exception:
        raise EvaluationError("invalid_manifest_or_leakage") from None


def load_manifest(path, *, root, public_vocabulary=None):
    try:
        selected = private_path(root, path)
        if selected.stat().st_size > 8_000_000:
            raise ValueError()
        manifest = Manifest.model_validate_json(selected.read_text(encoding="utf-8"))
        return validate_manifest(manifest, root=root, public_vocabulary=public_vocabulary)
    except Exception:
        raise EvaluationError("invalid_private_manifest") from None


def evidence_label(rows):
    return "personal_development_only" if len({r.speaker for r in rows}) == 1 else "consented_evaluation_not_automatically_generalizable"
