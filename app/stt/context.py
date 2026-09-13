"""Versioned hints: explicit loading, bounded budgets, no ground-truth access."""
import json
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PUBLIC_CONTEXT = Path(__file__).resolve().parents[2] / "data/stt/context-v1.json"


class Form(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    text: str = Field(min_length=1, max_length=80, repr=False, exclude=True)
    language: Literal["en", "hi", "mr", "mixed"]
    script: Literal["Latin", "Devanagari"]
    kind: Literal["canonical", "alias", "transliteration", "abbreviation", "alternate_spelling", "observed_asr_error"]
    provenance: Literal["public_example", "engineering_review", "user_confirmed"]
    review_status: Literal["reviewed", "pending"]
    hint_eligible: bool = True
    refinement_eligible: bool = False
    requires_confirmation: bool = True

    @model_validator(mode="after")
    def safe_form(self):
        if any(unicodedata.category(c) == "Cc" for c in self.text) or not self.text.strip():
            raise ValueError("invalid_form")
        if self.kind == "observed_asr_error" and (self.hint_eligible or not self.requires_confirmation):
            raise ValueError("unsafe_observed_variant")
        return self


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    entry_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$", repr=False)
    category: Literal["assistant", "application", "action", "location", "media"]
    forms: tuple[Form, ...] = Field(min_length=1, max_length=16, repr=False)


class Vocabulary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["1.0"]
    version: Literal["context-v1"]
    entries: tuple[Entry, ...] = Field(min_length=1, max_length=128, repr=False)

    @model_validator(mode="after")
    def unique_entries(self):
        if len({e.entry_id for e in self.entries}) != len(self.entries):
            raise ValueError("duplicate_entry")
        return self


class Hints(BaseModel):
    model_config = ConfigDict(frozen=True)
    initial_prompt: str = Field(default="", repr=False, exclude=True)
    hotwords: str = Field(default="", repr=False, exclude=True)
    version: str = "context-v1"
    status: Literal["ready", "tokenizer_unavailable", "tokenizer_error"]
    selected_count: int = 0
    token_count: int = 0
    # Language/script/kind only; no text, identifiers or private provenance strings.
    provenance: tuple[tuple[str, str, str], ...] = ()


def load_vocabulary(path=PUBLIC_CONTEXT):
    try:
        path = Path(path)
        if path.stat().st_size > 1_000_000:
            raise ValueError("oversize")
        return Vocabulary.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        raise ValueError("invalid_context") from None


def load_overlay(path, root):
    from app.evaluation.dataset import private_path
    return load_vocabulary(private_path(root, path))


def build_hints(vocabulary, language=None, *, tokenizer=None, overlay=None,
                prompt_limit=500, hotword_limit=300, token_limit=96):
    if language not in {None, "auto", "mixed", "en", "hi", "mr"}:
        raise ValueError("invalid_context_language")
    if not 0 <= prompt_limit <= 500 or not 0 <= hotword_limit <= 300 or not 0 <= token_limit <= 96:
        raise ValueError("invalid_context_budget")
    if tokenizer is None:
        return Hints(status="tokenizer_unavailable")
    entries = vocabulary.entries + (overlay.entries if overlay is not None else ())
    selected, seen, provenance = [], set(), []
    # One list avoids repeating the same hints in initial_prompt and hotwords.
    try:
        def count(text):
            encoded = tokenizer.encode(" " + text, add_special_tokens=False)
            ids = encoded.ids if hasattr(encoded, "ids") else encoded
            if not isinstance(ids, (list, tuple)) or not ids or any(type(i) is not int or i < 0 for i in ids):
                raise ValueError("invalid_tokenizer_result")
            return len(ids)
        tokens = 0
        for entry in entries:
            for form in entry.forms:
                if (not form.hint_eligible or form.kind == "observed_asr_error"
                        or form.review_status != "reviewed"):
                    continue
                if language in {"hi", "mr", "en"} and form.language not in {language, "mixed"}:
                    continue
                key = unicodedata.normalize("NFC", form.text).casefold().strip()
                if key in seen:
                    continue
                seen.add(key)
                candidate = ", ".join([*selected, form.text])
                cost = count(candidate)
                if len(candidate) <= hotword_limit and cost <= token_limit:
                    selected.append(form.text)
                    tokens = cost
                    provenance.append((form.language, form.script, form.kind))
        return Hints(hotwords=", ".join(selected), status="ready", selected_count=len(selected),
                     token_count=tokens, provenance=tuple(provenance))
    except Exception:
        return Hints(status="tokenizer_error")


def public_inspection(language=None):
    vocabulary = load_vocabulary()
    return {"version": vocabulary.version, "character_limits": {"initial_prompt": 500, "hotwords": 300},
            "token_limit": 96, "note": "Runtime hints require the loaded cached tokenizer.",
            "forms": [{"text": f.text, "language": f.language, "script": f.script, "kind": f.kind}
                      for e in vocabulary.entries for f in e.forms
                      if language in {None, "auto", "mixed"} or f.language in {language, "mixed"}]}
