"""Bounded typed plans; private input never appears in routine serialization."""
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

class PlanningError(Exception):
    def __init__(self, code="invalid_plan"):
        self.code = code if code in {"invalid_plan", "invalid_confirmation", "expired", "cancelled",
            "invalid_artifact", "consent_required", "already_exists", "size_limit", "unavailable"} else "invalid_plan"
        super().__init__(self.code)

class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True,
                              revalidate_instances="always")
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception:
            raise PlanningError() from None

class Configuration(Model):
    enabled: bool = True
    version: Literal["5a-v1"] = "5a-v1"
    max_steps: int = Field(default=10, ge=1, le=32, strict=True)
    max_depth: int = Field(default=8, ge=1, le=32, strict=True)
    max_retries: int = Field(default=1, ge=0, le=3, strict=True)
    step_timeout: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    total_timeout: float = Field(default=120, gt=0, le=600, allow_inf_nan=False)
    confirmation_expiry: int = Field(default=120, ge=1, le=600, strict=True)
    simulation_only: Literal[True] = True
    trace_root: Path | None = Field(default=None, repr=False, exclude=True)
    trace_saving_enabled: bool = False
    audio_saving_enabled: bool = False
    max_audio_duration: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    max_trace_bytes: int = Field(default=65536, ge=1024, le=262144, strict=True)
    session_limit: int = Field(default=5, ge=1, le=20, strict=True)

    @field_validator("max_steps", "max_depth", "max_retries", "confirmation_expiry", "max_trace_bytes", "session_limit", mode="before")
    @classmethod
    def integer(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdigit(): return int(value)
        return value

    @field_validator("step_timeout", "total_timeout", "max_audio_duration", mode="before")
    @classmethod
    def number(cls, value):
        if isinstance(value, bool): raise ValueError()
        return value

    @field_validator("simulation_only", mode="before")
    @classmethod
    def required(cls, value):
        if value is True or value == "true": return True
        raise ValueError()

    @model_validator(mode="after")
    def bounds(self):
        if self.step_timeout > self.total_timeout: raise ValueError()
        if self.trace_root is not None and (not self.trace_root.is_absolute() or ".." in self.trace_root.parts): raise ValueError()
        return self

class Capability(StrEnum):
    LAUNCH="application.launch"
    SEARCH="browser.search"
    READ="browser.read_results"
    COMPARE="research.compare"
    MEDIA_SEARCH="media.search"
    PLAY="media.play"
    CONTROL="media.control"
    VOLUME="system.volume"
    PRESENT="response.present"
    MESSAGE="communication.send"
    PAYMENT="financial.payment"
    DELETE="file.delete"
    SETTINGS="system.settings"
    CREDENTIALS="credentials.expose"
    SHELL="code.execute"

class Risk(StrEnum):
    INFORMATIONAL="informational"
    LOW="low"
    MODERATE="moderate"
    HIGH="high"
    PROHIBITED="prohibited"

class Arguments(Model):
    application: Literal["spotify","whatsapp","chrome","chrome_beta","youtube"] | None = None
    media: Literal["taare_zameen_par","taare_soundtrack"] | None = None
    control: Literal["pause","resume","stop","next","previous","volume_up","volume_down","mute","unmute"] | None = None

class Step(Model):
    step_id: str = Field(pattern=r"^step-[1-9][0-9]?$", max_length=7)
    order: int = Field(ge=1, le=32, strict=True)
    action: Literal["launch","search_media","play_media","control_media","volume","present","verify"]
    target: Literal["application","media","audio","response"]
    arguments: Arguments = Field(default_factory=Arguments)
    dependencies: tuple[str,...] = Field(default=(), max_length=32)
    capability: Capability
    risk: Risk
    requires_confirmation: bool
    timeout: float = Field(gt=0, le=60, allow_inf_nan=False)
    max_retries: int = Field(ge=0, le=3, strict=True)
    expected_observation: Literal["application_visible","media_candidates","playback_state","volume_state","help_visible"]
    verification_condition: Literal["simulated_observation_matches"] = "simulated_observation_matches"
    failure_behavior: Literal["retry_then_abort_dependents"] = "retry_then_abort_dependents"
    execution_permitted: Literal[False] = False

class Plan(Model):
    plan_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal["1.0"] = "1.0"
    planner_version: Literal["5a-v1"] = "5a-v1"
    trace_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    objective: str | None = Field(default=None, max_length=300, repr=False, exclude=True)
    source: object | None = Field(default=None, repr=False, exclude=True)
    authentication: Literal["unauthenticated_diagnostic","policy_verified"] = "unauthenticated_diagnostic"
    status: Literal["ready","needs_confirmation","unsupported","blocked","cancelled"]
    overall_risk: Risk
    requires_confirmation: bool
    steps: tuple[Step,...] = Field(default=(), max_length=32)
    reasons: tuple[Literal["planner_disabled","invalid_resolution","risk_blocked","unresolved_command","unsupported_application","unsupported_intent","fixed_template","planning_failed"],...] = Field(default=(), max_length=10)
    limitations: tuple[Literal["simulation_only","no_real_observations","no_execution_authority"],...] = (
        "simulation_only","no_real_observations","no_execution_authority")
    execution_permitted: Literal[False] = False

    @model_validator(mode="after")
    def structure(self):
        if self.created_at.utcoffset() is None or self.created_at.utcoffset().total_seconds()!=0: raise ValueError()
        if self.status=="ready" and not self.steps: raise ValueError()
        if self.status!="ready" and self.steps: raise ValueError()
        from app.planning.capabilities import assess_step
        seen=set()
        for i, step in enumerate(self.steps,1):
            if step.order!=i or step.step_id in seen: raise ValueError()
            if len(set(step.dependencies))!=len(step.dependencies) or any(d not in seen for d in step.dependencies): raise ValueError()
            expected=assess_step(step)
            if step.risk!=expected or step.requires_confirmation!=(expected in {Risk.MODERATE,Risk.HIGH,Risk.PROHIBITED}): raise ValueError()
            seen.add(step.step_id)
        if self.steps:
            actions=tuple(s.action for s in self.steps)
            if actions not in {("launch","verify"),("launch","search_media","play_media","verify"),
                               ("control_media","verify"),("volume","verify"),("present",)}: raise ValueError()
            if any(s.dependencies!=((self.steps[i-2].step_id,) if i>1 else ()) for i,s in enumerate(self.steps,1)): raise ValueError()
            if self.steps[-1].action=="verify" and self.steps[-1].expected_observation!=self.steps[-2].expected_observation: raise ValueError()
            if len(self.steps)==4 and (self.steps[0].arguments.application!="spotify" or self.steps[1].arguments.media!=self.steps[2].arguments.media): raise ValueError()
            order=list(Risk)
            if self.overall_risk!=max((s.risk for s in self.steps),key=order.index): raise ValueError()
            if self.requires_confirmation!=any(s.requires_confirmation for s in self.steps): raise ValueError()
        return self

class StepResult(Model):
    step_id: str = Field(pattern=r"^step-[1-9][0-9]?$",max_length=7)
    status: Literal["simulated_success","simulated_failure","blocked","cancelled"]
    attempts: int = Field(ge=0, le=4)
    observation: Literal["simulated_match","simulated_mismatch","not_observed"]
    recovery: Literal["none","retry_exhausted_abort","dependency_aborted"] = "none"
    execution_permitted: Literal[False] = False
    side_effect_occurred: Literal[False] = False

class Simulation(Model):
    status: Literal["simulated_success","simulated_failure","needs_confirmation","blocked","unsupported","cancelled"]
    steps: tuple[StepResult,...] = ()
    label: Literal["diagnostic/simulation; no side effect occurred"] = "diagnostic/simulation; no side effect occurred"
    execution_permitted: Literal[False] = False
    real_actions: Literal[0] = 0
