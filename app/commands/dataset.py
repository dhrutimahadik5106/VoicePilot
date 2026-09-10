"""Validate an explicitly selected local dataset; never collect recordings."""
import json
from pathlib import Path

from app.commands.models import DatasetRow, SLOTS
from app.commands.registry import DATA_DIR, load_registries


def load_dataset(path: Path = DATA_DIR / "seed-v1.jsonl"):
    if path.stat().st_size > 2_000_000:
        raise ValueError("Dataset exceeds seed-tool size limit")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(DatasetRow.model_validate_json(line))
        except ValueError:
            raise ValueError(f"Invalid dataset row {number}") from None
    if not rows or len(rows) > 10000:
        raise ValueError("Dataset must contain 1-10000 rows")
    if len({row.command_id for row in rows}) != len(rows):
        raise ValueError("Duplicate command ID")
    return rows


def validate_dataset(path: Path = DATA_DIR / "seed-v1.jsonl", directory: Path = DATA_DIR):
    rows = load_dataset(path)
    aliases, _ = load_registries(directory)
    known = {(entity.kind, entity.canonical_name) for entity in aliases.entities}
    for row in rows:
        for slot, value in row.entities.items():
            if (slot, value) not in known:
                raise ValueError("Expected entity is not in the independent registry")
    schema = json.loads((directory / "schema-v1.json").read_text(encoding="utf-8"))
    if schema != DatasetRow.model_json_schema():
        raise ValueError("Exported JSON Schema differs from the versioned contract")
    return rows
