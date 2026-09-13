"""Private annotations. Ordinary serialization intentionally excludes private fields."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.commands.models import Intent, SLOTS, render_command


class EvaluationRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    recording_id: str = Field(pattern=r"^rec_[a-z0-9]{8,64}$", repr=False, exclude=True)
    source_type: Literal["synthetic_text", "consented_recording"]
    audio: str | None = Field(default=None, repr=False, exclude=True)
    audio_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False, exclude=True)
    ground_truth: str = Field(max_length=2000, repr=False, exclude=True)
    review_status: Literal["reviewed"]
    language: Literal["en", "hi", "mr", "mixed"]
    script: Literal["Latin", "Devanagari", "mixed"]
    speaker: str = Field(pattern=r"^spk_[a-f0-9]{16}$", repr=False, exclude=True)
    session: str = Field(pattern=r"^session_[a-z0-9]{8,64}$", repr=False, exclude=True)
    recording_group: str = Field(pattern=r"^group_[a-z0-9]{8,64}$", repr=False, exclude=True)
    split: Literal["development", "validation", "test"]
    noise_condition: Literal["quiet", "background_speech", "music", "street", "unknown"]
    consent_reference: str | None = Field(default=None, pattern=r"^consent_[a-z0-9]{8,64}$", repr=False, exclude=True)
    evaluation_permitted: bool = False
    retention_review_date: str | None = Field(default=None, repr=False, exclude=True)
    content: Literal["speech", "non_speech"]
    usable_speech: bool
    task: Literal["dictation", "command"]
    expected_intent: Intent | None = None
    expected_entities: dict[str, str] = Field(default_factory=dict, repr=False, exclude=True)
    expected_canonical: str | None = Field(default=None, max_length=500, repr=False, exclude=True)
    expected_confirmation: bool = True

    @model_validator(mode="after")
    def valid_source(self):
        if self.source_type == "consented_recording":
            if not all((self.audio, self.audio_sha256, self.consent_reference,
                        self.evaluation_permitted, self.retention_review_date)):
                raise ValueError("missing_consent_or_audio_metadata")
            from datetime import date
            date.fromisoformat(self.retention_review_date)
        elif self.audio or self.audio_sha256 or self.consent_reference or self.evaluation_permitted:
            raise ValueError("synthetic_text_must_not_claim_consent_or_audio")
        if self.content == "non_speech" and (self.ground_truth or self.usable_speech):
            raise ValueError("invalid_non_speech_annotation")
        if self.content == "speech" and not self.ground_truth.strip():
            raise ValueError("missing_speech_reference")
        if self.task == "dictation" and (self.expected_intent or self.expected_entities or self.expected_canonical):
            raise ValueError("dictation_has_no_command_label")
        if self.task == "command":
            if self.expected_intent is None:
                if self.expected_entities or self.expected_canonical or not self.expected_confirmation:
                    raise ValueError("unknown_command_requires_abstention")
            else:
                required = SLOTS.get(self.expected_intent)
                allowed = {required} if required else set()
                if self.expected_intent == Intent.PLAY_MEDIA:
                    allowed.add("application")
                if (set(self.expected_entities) - allowed or
                        any(not value.strip() or len(value) > 160 for value in self.expected_entities.values())):
                    raise ValueError("invalid_expected_entities")
                if required and required not in self.expected_entities:
                    if self.expected_canonical is not None or not self.expected_confirmation:
                        raise ValueError("incomplete_command_requires_confirmation")
                elif self.expected_canonical != render_command(self.expected_intent, self.expected_entities):
                    raise ValueError("inconsistent_expected_command")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["1.0"]
    rows: tuple[EvaluationRow, ...] = Field(min_length=1, max_length=10000, repr=False, exclude=True)
