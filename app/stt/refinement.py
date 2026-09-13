"""Shadow-only, whole-utterance courtesy spelling proposals. Never resolver input."""
from pydantic import BaseModel, ConfigDict, Field

RULE_VERSION = "shadow-v1"
# Deliberately narrow: no free-form substitution inside sentences or entity spans.
RULES = {
    "\u0915\u0943 \u092a\u092f\u093e": ("\u0915\u0943\u092a\u092f\u093e", "courtesy_boundary_1"),
    "\u0927\u0928\u094d\u092f \u0935\u093e\u0926": ("\u0927\u0928\u094d\u092f\u0935\u093e\u0926", "courtesy_boundary_2"),
}


class Change(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: int
    end: int
    rule_id: str
    evidence_category: str = "reviewed_engineering_rule_not_calibrated"
    alternatives: tuple[str, ...] = Field(repr=False, exclude=True)
    requires_confirmation: bool = True


class Refinement(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw_transcript: str = Field(repr=False, exclude=True)
    normalized_transcript: str = Field(repr=False, exclude=True)
    refined_transcript: str | None = Field(default=None, repr=False, exclude=True)
    changes: tuple[Change, ...] = ()
    requires_confirmation: bool = False
    rule_set_version: str = RULE_VERSION
    source_view: str = "normalized_transcript"
    mode: str = "shadow_only"

    def inspection(self):
        return {**self.model_dump(), "raw_transcript": self.raw_transcript,
                "normalized_transcript": self.normalized_transcript,
                "refined_transcript": self.refined_transcript,
                "changes": [{**c.model_dump(), "alternatives": list(c.alternatives)} for c in self.changes]}


def refine(result):
    if result.status != "succeeded":
        return Refinement(raw_transcript="", normalized_transcript="")
    raw, normalized = result.raw_transcript, result.normalized_transcript
    proposed = RULES.get(normalized) if result.language in {"hi", "mr"} else None
    if proposed is None:
        return Refinement(raw_transcript=raw, normalized_transcript=normalized)
    text, rule = proposed
    return Refinement(raw_transcript=raw, normalized_transcript=normalized,
                      refined_transcript=text, requires_confirmation=True,
                      changes=(Change(start=0, end=len(normalized), rule_id=rule,
                                      alternatives=(normalized, text)),))
