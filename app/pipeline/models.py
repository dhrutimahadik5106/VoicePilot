"""Allowlisted trace with explicit private text projection."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field, model_validator
from app.planning.models import Model, Plan, Simulation
from app.planning.risk import SENSITIVE

class Details(Model):
    raw_transcript: str = Field(max_length=8192,repr=False)
    stt_normalized_transcript: str = Field(max_length=8192,repr=False)
    resolver_normalized_transcript: str = Field(max_length=8192,repr=False)
    entities: dict[Literal["application","media"],str] = Field(default_factory=dict,repr=False)
    canonical_command: str | None = Field(default=None,max_length=300,repr=False)
    proposed_objective: str | None = Field(default=None,max_length=300,repr=False)

    @model_validator(mode="after")
    def private_fields(self):
        import json
        if any(not v or len(v)>160 for v in self.entities.values()): raise ValueError()
        if SENSITIVE.search(json.dumps(self.model_dump(),ensure_ascii=False)): raise ValueError()
        return self


class Trace(Model):
    schema_version: Literal["5a-trace-v1"] = "5a-trace-v1"
    trace_id: UUID = Field(default_factory=uuid4)
    session_id: UUID = Field(default_factory=uuid4)
    utc_timestamp: datetime = Field(default_factory=lambda:datetime.now(timezone.utc))
    local_timestamp: datetime = Field(default_factory=lambda:datetime.now().astimezone())
    mode: Literal["unauthenticated-text","unauthenticated-voice","authenticated"]
    label: Literal["diagnostic/simulation; unsuitable for production authorization"] = "diagnostic/simulation; unsuitable for production authorization"
    authentication: Literal["unauthenticated_diagnostic","denied","policy_verified"] = "unauthenticated_diagnostic"
    status: Literal["completed","blocked","cancelled"]
    reason: Literal["ok","cancelled","invalid_input","unsuccessful_stt","access_denied","pipeline_failed","sensitive_input"]
    duration: float = Field(default=0,ge=0,le=120,allow_inf_nan=False)
    sample_rate: int = Field(default=0,ge=0,le=48000)
    channels: int = Field(default=0,ge=0,le=2)
    stt_status: Literal["not_called","succeeded","failed","unusable_audio","cancelled"] = "not_called"
    language: str | None = Field(default=None,pattern=r"^[a-z]{2,3}$")
    resolver_status: Literal["not_called","resolved","needs_confirmation","unknown"] = "not_called"
    resolver_reasons: tuple[Literal["empty_transcript","negated_command","compound_command","unsupported_command",
        "ambiguous_intent","missing_entity","unknown_entity","ambiguous_entity","fuzzy_entity_suggestion",
        "observed_asr_error","alias_requires_confirmation","low_heuristic_score","observed_address_form",
        "spotify_play_workflow","exact_entity_match","exact_intent_pattern","unsuccessful_stt"],...] = ()
    resolver_evidence: tuple[Literal["canonical","alias","shorthand","observed_asr_error","fuzzy"],...] = ()
    registry_version: Literal["1.0"] = "1.0"
    intent: Literal["open_application","play_media","pause","resume","stop","next","previous","volume_up","volume_down","mute","unmute","help"] | None = None
    plan: Plan | None = None
    simulation: Simulation | None = None
    capture_seconds: float = Field(default=0,ge=0,allow_inf_nan=False)
    stt_seconds: float = Field(default=0,ge=0,allow_inf_nan=False)
    planning_seconds: float = Field(default=0,ge=0,allow_inf_nan=False)
    total_seconds: float = Field(default=0,ge=0,allow_inf_nan=False)
    audio_saved: bool = False
    execution_permitted: Literal[False] = False
    real_actions: Literal[0] = 0
    details: Details | None = Field(default=None,repr=False,exclude=True)

    @model_validator(mode="after")
    def validate_trace(self):
        if self.utc_timestamp.utcoffset() is None or self.utc_timestamp.utcoffset().total_seconds()!=0 or self.local_timestamp.utcoffset() is None: raise ValueError()
        if self.mode!="authenticated" and self.authentication!="unauthenticated_diagnostic": raise ValueError()
        if self.mode=="authenticated" and self.authentication=="unauthenticated_diagnostic": raise ValueError()
        if self.authentication=="denied" and (self.stt_status!="not_called" or self.plan is not None or self.details is not None): raise ValueError()
        if self.plan is not None and (self.plan.trace_id!=self.trace_id or self.plan.authentication!=self.authentication): raise ValueError()
        if self.status=="cancelled" and (self.details is not None or self.plan is not None or self.simulation is not None): raise ValueError()
        return self

    def public(self, *, include_text=False):
        result=self.model_dump(mode="json")
        if include_text and self.details is not None and not SENSITIVE.search(self.details.raw_transcript):
            result["details"]=self.details.model_dump(mode="json")
        return result
