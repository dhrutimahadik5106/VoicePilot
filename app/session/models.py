"""Closed frontend contracts. No capture, profile lookup or network on import."""
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field, field_validator
from app.planning.models import Model


class SessionError(Exception):
    def __init__(self, code="invalid_request"):
        codes = {"invalid_request", "invalid_transition", "not_found", "capacity", "expired", "replayed",
                 "binding_mismatch", "calibration_blocked", "disabled", "cancelled", "emergency_stop",
                 "reset_unavailable", "unsupported", "speaker_rejected", "verification_failed", "ok"}
        self.code = code if code in codes else "invalid_request"
        super().__init__(self.code)


class Configuration(Model):
    enabled: bool = False
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173",)
    demo_enabled: bool = True
    max_sessions: int = Field(default=16, ge=1, le=64)
    max_events: int = Field(default=64, ge=24, le=256)
    max_history: int = Field(default=100, ge=1, le=1000)
    session_timeout: int = Field(default=120, ge=10, le=300)
    clarification_expiry: int = Field(default=30, ge=1, le=45)
    max_request_bytes: int = Field(default=4096, ge=256, le=16384)
    transcript_display: bool = False
    waveform_enabled: bool = True
    production_enabled: Literal[False] = False
    tts_enabled: Literal[False] = False
    wake_word_enabled: Literal[False] = False
    permanent_history_enabled: Literal[False] = False

    @field_validator("port", "max_sessions", "max_events", "max_history", "session_timeout", "clarification_expiry", "max_request_bytes", mode="before")
    @classmethod
    def integers(cls, value):
        if type(value) is str and value.isascii() and value.isdigit(): return int(value)
        if type(value) is not int: raise ValueError()
        return value

    @field_validator("allowed_origins")
    @classmethod
    def origins(cls, value):
        import re
        if not 1 <= len(value) <= 4 or len(value) != len(set(value)):
            raise ValueError()
        for origin in value:
            match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{4,5})", origin)
            if match is None or not 1024 <= int(match[1]) <= 65535:
                raise ValueError()
        return value

    @field_validator("production_enabled", "tts_enabled", "wake_word_enabled", "permanent_history_enabled", mode="before")
    @classmethod
    def disabled(cls, value):
        if value is False or value == "false": return False
        raise ValueError()


class State(StrEnum):
    IDLE="idle"
    READY="ready"
    ACTIVATION="awaiting_activation"
    LISTENING="listening"
    AUTHENTICATING="authenticating"
    UNDERSTANDING="understanding"
    CLARIFICATION="needs_clarification"
    PLANNING="planning"
    RISK="risk_checking"
    CONFIRMATION="awaiting_confirmation"
    AUTHORIZED="authorized"
    EXECUTING="executing"
    OBSERVING="observing"
    VERIFYING="verifying"
    RESPONDING="responding"
    COMPLETED="completed"
    BLOCKED="blocked"
    CANCELLED="cancelled"
    TIMED_OUT="timed_out"
    FAILED="failed"
    STOPPED="emergency_stopped"


Risk = Literal["informational","safe","low","sensitive","high","destructive","forbidden","unsupported"]
Policy = Literal["allowed","confirmation_required","blocked","prohibited","unsupported","calibration_blocked","disabled"]
Scenario = Literal["read_volume","calculator_confirm","chrome_cancel","ambiguous_application","unknown_application",
                   "wrong_speaker","confirmation_expiry","emergency_stop","verification_failure","history_entry"]


class DemoMarker(Model):
    mode: Literal["synthetic_demo"] = "synthetic_demo"
    simulation: Literal[True] = True
    execution_permitted: Literal[False] = False
    real_actions: Literal[0] = 0
    banner: Literal["DEMO / SIMULATION — NO REAL ACTION"] = "DEMO / SIMULATION — NO REAL ACTION"


class Candidate(Model):
    candidate_id: Literal["notepad","calculator","chrome"]
    display_name: Literal["Notepad","Calculator","Chrome"]


class Card(Model):
    request_id: UUID = Field(default_factory=uuid4)
    prompt_code: Literal["choose_application","confirm_synthetic_action"]
    reason: Literal["ambiguous_application","state_change"]
    candidates: tuple[Candidate, ...] = Field(default=(), max_length=3)
    expires_in_seconds: float = Field(ge=0, le=300)


class TTS(Model):
    available: Literal[False] = False
    speaking_permitted: Literal[False] = False
    speech_enabled_preference: Literal[False] = False
    sensitivity: Literal["public_safe"] = "public_safe"
    response_code: Literal["ready","completed","blocked","cancelled","expired","verification_failed"] = "ready"


class View(DemoMarker):
    session_id: UUID
    state: State
    state_label: str = Field(pattern=r"^[a-z_]{1,32}$")
    listening: bool = False
    authentication: Literal["unavailable","pending_calibration","verifying","authorized","rejected","synthetic_demo"] = "synthetic_demo"
    transcript_visibility: Literal["hidden","transient_synthetic"] = "hidden"
    transcript: str | None = Field(default=None, max_length=120)
    corrected_interpretation: str | None = Field(default=None, max_length=80)
    canonical_command: str | None = Field(default=None, max_length=80)
    risk: Risk = "unsupported"
    policy: Policy = "disabled"
    risk_explanation: Literal["not_planned","informational_read","reversible_action","unsupported_command"] = "not_planned"
    plan_summary: tuple[str, ...] = Field(default=(), max_length=3)
    conversation: Literal["resolved","needs_clarification","needs_confirmation","cancelled","unsupported","blocked"] = "blocked"
    clarification: Card | None = None
    confirmation: Card | None = None
    confirmation_mode: Literal["synthetic_ui_demo"] = "synthetic_ui_demo"
    waveform: tuple[float, ...] = Field(default=(), max_length=8)
    progress: int = Field(default=0, ge=0, le=100)
    verified: bool = False
    reason: str = Field(default="ok", pattern=r"^[a-z_]{1,40}$")
    duration_seconds: float = Field(default=0, ge=0, le=3600)
    final_response: Literal["Ready", "Completed in simulation", "Blocked", "Cancelled", "Expired", "Verification failed"] = "Ready"
    tts: TTS = Field(default_factory=TTS)
    emergency_stopped: bool = False

    @field_validator("waveform")
    @classmethod
    def waveform_bounds(cls, value):
        if any(not 0 <= number <= 1 for number in value): raise ValueError()
        return value


class PublicEvent(DemoMarker):
    sequence: int = Field(ge=1)
    session_id: UUID
    state: State
    reason: str = Field(pattern=r"^[a-z_]{1,40}$")


class HistoryEntry(DemoMarker):
    session_id: UUID
    timestamp: str = Field(max_length=40)
    capability: str = Field(max_length=60)
    state: State
    risk: Risk
    confirmation_required: bool
    confirmation_received: bool
    verified: bool
    duration_seconds: float = Field(ge=0, le=3600)
    reason: str = Field(pattern=r"^[a-z_]{1,40}$")
