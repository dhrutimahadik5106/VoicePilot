"""Strict bounded API bodies and public response documents."""
from typing import Literal
from uuid import UUID
from pydantic import Field
from app.planning.models import Model
from app.session.models import Scenario, DemoMarker, PublicEvent, HistoryEntry
from app.session.catalog import CapabilityView


class Empty(Model):
    pass


class CreateDemo(Model):
    scenario: Scenario
    show_transcript: bool = Field(default=False, strict=True)


class Clarify(Model):
    request_id: UUID
    candidate_id: Literal["notepad","calculator","chrome"]


class Confirm(Model):
    request_id: UUID
    decision: Literal["confirm","cancel"]


class Status(Model):
    api_version: Literal["v1"] = "v1"
    production_available: Literal[False] = False
    production_authentication: Literal["pending_calibration"] = "pending_calibration"
    calibration_inspected: Literal[False] = False
    confirmation_mode: Literal["speaker_verified_voice"] = "speaker_verified_voice"
    emergency_stopped: bool = False
    emergency_reset_available: Literal[False] = False
    tts_available: Literal[False] = False
    wake_word_available: Literal[False] = False
    global_shortcut_available: Literal[False] = False
    capture_on_startup: Literal[False] = False


class Catalog(Model):
    capabilities: tuple[CapabilityView, ...] = Field(max_length=40)


class Privacy(Model):
    transcript_default: Literal["hidden"] = "hidden"
    storage: Literal["bounded_process_memory"] = "bounded_process_memory"
    production_audio_available: Literal[False] = False
    waveform: Literal["synthetic_eight_levels_four_updates_per_second"] = "synthetic_eight_levels_four_updates_per_second"
    history_limit: int = Field(ge=1,le=1000)
    event_limit: int = Field(ge=24,le=256)


class Events(DemoMarker):
    events: tuple[PublicEvent, ...] = Field(max_length=256)
    first_sequence: int = Field(ge=0)
    last_sequence: int = Field(ge=0)


class History(DemoMarker):
    entries: tuple[HistoryEntry, ...] = Field(max_length=1000)
    retention: Literal["current_process_only"] = "current_process_only"
    limit: int = Field(ge=1,le=1000)


class Acknowledged(DemoMarker):
    result: Literal["deleted","cleared","emergency_stopped"]


class Error(DemoMarker):
    error: Literal["invalid_request","invalid_transition","not_found","capacity","expired","replayed",
        "binding_mismatch","calibration_blocked","disabled","cancelled","emergency_stop","reset_unavailable",
        "unsupported","speaker_rejected","verification_failed","method_not_allowed","origin_denied",
        "host_denied","content_type","body_limit","unavailable"]
