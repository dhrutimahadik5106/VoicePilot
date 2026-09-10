"""Explicit, bounded registry loading; matching rules are independent of seed rows."""
import json
import re
import unicodedata
from pathlib import Path

from pydantic import Field, model_validator
from typing import Literal

from app.commands.models import Contract, Intent, Language, SLOTS, TEMPLATES, render_command

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "commands"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold().replace("’", "'")
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    # Keep apostrophes for negation; keep letters/combining marks in Indic scripts.
    text = "".join(" " if unicodedata.category(char).startswith("P") and char != "'" else char for char in text)
    return " ".join(text.split())


class Alias(Contract):
    text: str = Field(min_length=1, max_length=160)
    language: Language
    kind: Literal["alias", "shorthand", "observed_asr_error"]
    provenance: str = Field(min_length=1, max_length=400)
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def validate_observed(self):
        if not normalize(self.text):
            raise ValueError("Empty normalized alias")
        if self.kind in {"observed_asr_error", "shorthand"} and not self.requires_confirmation:
            raise ValueError("Observed errors and shorthand require explicit confirmation")
        return self


class Entity(Contract):
    entity_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    canonical_name: str = Field(min_length=1, max_length=160)
    kind: Literal["assistant", "application", "media"]
    aliases: tuple[Alias, ...]


class AliasRegistry(Contract):
    schema_version: Literal["1.0"]
    entities: tuple[Entity, ...]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({item.entity_id for item in self.entities}) != len(self.entities):
            raise ValueError("Duplicate entity IDs")
        return self


class Pattern(Contract):
    text: str = Field(min_length=1, max_length=200)
    language: Language


class IntentSpec(Contract):
    intent: Intent
    patterns: tuple[Pattern, ...]

    @model_validator(mode="after")
    def safe_patterns(self):
        slot = SLOTS.get(self.intent)
        for pattern in self.patterns:
            slots = re.findall(r"{([^{}]+)}", pattern.text)
            if slots != ([slot] if slot else []):
                raise ValueError("Pattern must contain precisely its intent's entity slot")
        return self


class IntentRegistry(Contract):
    schema_version: Literal["1.0"]
    intents: tuple[IntentSpec, ...]

    @model_validator(mode="after")
    def unique_intents(self):
        values = [item.intent for item in self.intents]
        if len(set(values)) != len(values) or set(values) != set(Intent):
            raise ValueError("Registry must define each supported intent once")
        return self


def read_json(path: Path):
    if path.stat().st_size > 1_000_000:
        raise ValueError("Registry exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def load_registries(directory: Path = DATA_DIR):
    return (
        AliasRegistry.model_validate(read_json(directory / "aliases-v1.json")),
        IntentRegistry.model_validate(read_json(directory / "intents-v1.json")),
    )


def canonical_command(intent, entities):
    return render_command(intent, entities)
