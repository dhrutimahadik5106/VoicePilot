"""Versioned dataset and non-executing resolution contracts."""
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Language = Literal["en", "hi", "mr", "mixed"]


class Intent(StrEnum):
    OPEN_APPLICATION = "open_application"
    PLAY_MEDIA = "play_media"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    NEXT = "next"
    PREVIOUS = "previous"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    UNMUTE = "unmute"
    HELP = "help"


SLOTS = {Intent.OPEN_APPLICATION: "application", Intent.PLAY_MEDIA: "media"}
TEMPLATES = {
    Intent.OPEN_APPLICATION: "Open {application}", Intent.PLAY_MEDIA: "Play {media}",
    Intent.PAUSE: "Pause playback", Intent.RESUME: "Resume playback",
    Intent.STOP: "Stop playback", Intent.NEXT: "Next track", Intent.PREVIOUS: "Previous track",
    Intent.VOLUME_UP: "Increase volume", Intent.VOLUME_DOWN: "Decrease volume",
    Intent.MUTE: "Mute audio", Intent.UNMUTE: "Unmute audio", Intent.HELP: "Show help",
}


def render_command(intent, entities):
    """Format a proposal while retaining optional play-application context."""
    slot = SLOTS.get(intent)
    if slot is not None and slot not in entities:
        return None
    proposal = TEMPLATES[intent].format(**entities)
    if intent == Intent.PLAY_MEDIA and "application" in entities:
        proposal += " on " + entities["application"]
    return proposal


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetRow(Contract):
    schema_version: Literal["1.0"]
    command_id: str = Field(pattern=r"^vp3b-[a-z0-9-]+$", max_length=80)
    language: Language
    input_transcript: str = Field(min_length=1, max_length=500, repr=False)
    canonical_intent: Intent | None
    entities: dict[str, str]
    canonical_command: str | None = Field(repr=False)
    variation_type: Literal["canonical", "paraphrase", "alias", "mixed_language",
                            "observed_asr_error", "unknown_entity", "incomplete",
                            "negated", "compound", "ambiguous", "unknown", "typo"]
    expected_confirmation_requirement: bool
    source_type: Literal["synthetic_text", "consented_recording"]
    anonymous_speaker_id: str | None = Field(default=None, pattern=r"^spk_[0-9a-f]{16}$")
    noise_condition: Literal["quiet", "background_speech", "music", "street", "unknown"] | None = None
    consent_reference: str | None = Field(default=None, pattern=r"^consent_[a-z0-9]{8,64}$")

    @model_validator(mode="after")
    def validate_semantics(self):
        if not self.input_transcript.strip():
            raise ValueError("Transcript cannot be blank")
        if self.source_type == "synthetic_text":
            if any(value is not None for value in
                   (self.anonymous_speaker_id, self.noise_condition, self.consent_reference)):
                raise ValueError("Synthetic text must not claim speaker, noise or recording consent")
        elif self.anonymous_speaker_id is None or self.consent_reference is None:
            raise ValueError("Recorded sources require pseudonymous speaker and consent reference")
        if self.canonical_intent is None:
            if self.entities or self.canonical_command is not None or not self.expected_confirmation_requirement:
                raise ValueError("Unknown commands require abstention")
        else:
            slot = SLOTS.get(self.canonical_intent)
            allowed = {slot} if slot else set()
            if self.canonical_intent == Intent.PLAY_MEDIA:
                allowed.add("application")
            if set(self.entities) - allowed:
                raise ValueError("Unexpected entity slot")
            if any(not value.strip() or len(value) > 160 for value in self.entities.values()):
                raise ValueError("Invalid entity")
            if slot and slot not in self.entities:
                if self.canonical_command is not None or not self.expected_confirmation_requirement:
                    raise ValueError("Incomplete entities require confirmation")
            elif self.canonical_command != render_command(self.canonical_intent, self.entities):
                raise ValueError("Canonical command does not match intent/entities")
        if self.variation_type in {"observed_asr_error", "unknown_entity", "incomplete",
                                    "negated", "compound", "ambiguous", "unknown", "typo"}:
            if not self.expected_confirmation_requirement:
                raise ValueError("Challenging examples require confirmation")
        return self


class ResolverConfig(Contract):
    acceptance_threshold: float = Field(default=.95, ge=.9, le=1, allow_inf_nan=False)
    ambiguity_margin: float = Field(default=.08, ge=0, le=.5, allow_inf_nan=False)
    suggestion_threshold: float = Field(default=.65, ge=.5, le=.9, allow_inf_nan=False)
    max_candidates: int = Field(default=5, ge=2, le=10, strict=True)


class Candidate(Contract):
    entity_id: str
    canonical_name: str
    entity_kind: Literal["assistant", "application", "media"]
    matched_alias: str
    match_type: Literal["canonical", "alias", "shorthand", "observed_asr_error", "fuzzy"]
    heuristic_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_confirmation: bool
    provenance: str


class Resolution(Contract):
    raw_transcript: str = Field(repr=False, strict=True)
    normalized_transcript: str = Field(repr=False)
    language: Language
    intent: Intent | None = None
    entities: dict[str, str] = Field(default_factory=dict)
    canonical_command: str | None = Field(default=None, repr=False)
    heuristic_score: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    score_kind: Literal["heuristic_match_score"] = "heuristic_match_score"
    candidates: tuple[Candidate, ...] = ()
    status: Literal["resolved", "needs_confirmation", "unknown"]
    requires_confirmation: bool
    reasons: tuple[str, ...]
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.status != "resolved" and not self.requires_confirmation:
            raise ValueError("Unresolved proposals require confirmation")
        if self.status == "resolved" and (self.requires_confirmation or self.canonical_command is None):
            raise ValueError("Resolved interpretation must have a complete proposal")
        return self
