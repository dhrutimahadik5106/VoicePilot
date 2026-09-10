import json

import pytest

from app.commands.dataset import load_dataset, validate_dataset
from app.commands.models import DatasetRow
from app.commands.registry import DATA_DIR


def test_seed_valid_and_synthetic_only():
    rows = validate_dataset()
    assert len(rows) == 80
    assert {row.language for row in rows} == {"en", "hi", "mr", "mixed"}
    assert len({row.canonical_intent for row in rows if row.canonical_intent}) == 12
    assert all(row.source_type == "synthetic_text" and row.anonymous_speaker_id is None
               and row.noise_condition is None for row in rows)
    kinds = {row.variation_type for row in rows}
    assert {"unknown_entity", "incomplete", "negated", "compound", "ambiguous"}.issubset(kinds)


def test_exported_schema_matches_contract():
    schema = json.loads((DATA_DIR / "schema-v1.json").read_text(encoding="utf-8"))
    assert schema == DatasetRow.model_json_schema()


def test_duplicate_dataset_ids_rejected(tmp_path):
    line = (DATA_DIR / "seed-v1.jsonl").read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(line + "\n" + line, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate command ID"):
        load_dataset(path)


def test_invalid_dataset_error_does_not_echo_content(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text('{"private": "sensitive transcript"}', encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_dataset(path)
    assert str(error.value) == "Invalid dataset row 1"
