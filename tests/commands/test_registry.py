import json

import pytest
from pydantic import ValidationError

from app.commands.registry import Alias, AliasRegistry, DATA_DIR, load_registries, normalize


def test_observed_error_is_traceable_and_confirmation_required():
    aliases, intents = load_registries()
    assert len(intents.intents) == 12
    target = next(item for item in aliases.entities if item.entity_id == "taare_zameen_par")
    observed = next(a for a in target.aliases if a.text == "Tharism Infer")
    assert observed.kind == "observed_asr_error" and observed.requires_confirmation
    assert "User-observed ASR error" in observed.provenance
    assert "not a genuine pronunciation" in observed.provenance


def test_observed_alias_cannot_disable_confirmation():
    with pytest.raises(ValidationError):
        Alias(text="Tharism Infer", language="en", kind="observed_asr_error",
              provenance="User report", requires_confirmation=False)


def test_duplicate_entity_id_rejected():
    registry = json.loads((DATA_DIR / "aliases-v1.json").read_text(encoding="utf-8"))
    registry["entities"].append(registry["entities"][0])
    with pytest.raises(ValidationError):
        AliasRegistry.model_validate(registry)


def test_normalization_preserves_indic_marks_and_negation():
    assert normalize("  व्हॉइस पायलट,  Spotify! ") == "व्हॉइस पायलट spotify"
    assert normalize("Don’t open Spotify") == "don't open spotify"


def test_registry_independent_of_seed(monkeypatch):
    from pathlib import Path
    original = Path.read_text
    def read(path, *args, **kwargs):
        assert path.name != "seed-v1.jsonl"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    from app.commands.resolver import CommandResolver
    assert CommandResolver.from_directory().resolve("open Spotify").status == "resolved"

def test_observed_provenance_spacing(resolver):
    candidate = resolver.resolve("open Spotify and play Tharism Infer").candidates[0]
    assert "Phase 3B instructions" in candidate.provenance
    assert "Phase 3Binstructions" not in candidate.provenance
    assert candidate.match_type == "observed_asr_error"
    assert candidate.requires_confirmation
