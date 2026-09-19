"""Closed launch contracts; no speech, paths or arbitrary arguments in public data."""
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field, field_validator, model_validator
from app.planning.models import Model
from app.execution.models import AuditEvent, State

AppId = Literal["notepad", "calculator", "chrome", "spotify"]


class Status(StrEnum):
    AVAILABLE = "available"
    LAUNCHED = "launched_and_verified"
    ALREADY_RUNNING = "already_running_and_verified"
    LAUNCH_FAILED = "launch_failed"
    NOT_INSTALLED = "application_not_installed"
    IDENTITY_MISMATCH = "identity_mismatch"
    OBSERVATION_UNAVAILABLE = "observation_unavailable"
    VERIFICATION_FAILED = "verification_failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    EMERGENCY_STOPPED = "emergency_stopped"
    ACCESS_DENIED = "access_denied"
    UNSUPPORTED = "unsupported_application"
    INVALID_AUTHORIZATION = "invalid_authorization"
    DISABLED = "disabled"


class LaunchError(Exception):
    def __init__(self, status=Status.LAUNCH_FAILED):
        self.status = status if isinstance(status, Status) else Status.LAUNCH_FAILED
        super().__init__(self.status.value)


class Configuration(Model):
    real_execution_enabled: bool = False
    windows_adapter_enabled: bool = True
    manual_launch_testing_enabled: bool = True
    approved_application_ids: tuple[AppId, ...] = Field(default=("notepad", "calculator", "chrome", "spotify"), min_length=1, max_length=4)
    discovery_timeout: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    launch_timeout: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    observation_timeout: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    authorization_expiry: int = Field(default=30, ge=1, le=60)
    maximum_applications: Literal[1] = 1
    arguments_allowed: Literal[False] = False
    elevation_allowed: Literal[False] = False

    @field_validator("approved_application_ids")
    @classmethod
    def unique_apps(cls, value):
        if len(value) != len(set(value)):
            raise ValueError()
        return value

    @field_validator("maximum_applications", "arguments_allowed", "elevation_allowed", mode="before")
    @classmethod
    def immutable(cls, value, info):
        expected = 1 if info.field_name == "maximum_applications" else False
        if type(value) is type(expected) and value == expected or value == str(expected).lower():
            return expected
        raise ValueError()

    @field_validator("discovery_timeout", "launch_timeout", "observation_timeout", "authorization_expiry", mode="before")
    @classmethod
    def numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError()
        return value


class Entry(Model):
    application_id: AppId
    display_name: Literal["Notepad", "Calculator", "Google Chrome", "Spotify"]
    version: Literal["6a-v1"] = "6a-v1"
    executable_names: tuple[str, ...]
    original_filenames: tuple[str, ...]
    publishers: tuple[str, ...]
    discovery: tuple[Literal["system_directory", "program_files"], ...]
    path_constraint: Literal["protected_system_or_program_files"] = "protected_system_or_program_files"
    capability: Literal["application.launch"] = "application.launch"
    observation: Literal["independent_approved_process_identity"] = "independent_approved_process_identity"
    arguments_allowed: Literal[False] = False
    elevation_allowed: Literal[False] = False
    phase_status: Literal["conditional_on_verified_installation"] = "conditional_on_verified_installation"


class Discovery(Model):
    application_id: AppId
    status: Status
    identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)


class LaunchPlan(Model):
    plan_id: UUID = Field(default_factory=uuid4)
    step_id: Literal["step-1"] = "step-1"
    application_id: AppId
    identity: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)
    capability: Literal["application.launch"] = "application.launch"
    policy_version: Literal["6a-v1"] = "6a-v1"
    mode: Literal["manual_operator_test", "authenticated_voice"] = "manual_operator_test"
    authentication_id: UUID | None = Field(default=None, repr=False, exclude=True)
    arguments_allowed: Literal[False] = False
    elevation_allowed: Literal[False] = False


class Permit(Model):
    handle: UUID = Field(default_factory=uuid4, repr=False, exclude=True)


class LaunchAudit(AuditEvent):
    reason: Status
    fake: Literal[False] = False
    execution_permitted: bool = False


class LaunchResult(Model):
    status: Status
    state: State
    application_id: AppId | None = None
    mode: Literal["manual_operator_test", "authenticated_voice", "authenticated_denied"] = "manual_operator_test"
    process_creation_attempted: bool = False
    process_observed: bool = False
    foreground_verified: Literal[False] = False
    rollback_attempted: Literal[False] = False
    execution_permitted: bool = False
    events: tuple[LaunchAudit, ...] = ()


    @model_validator(mode="after")
    def verified_result(self):
        success = self.status in {Status.LAUNCHED, Status.ALREADY_RUNNING}
        if success != (self.state == State.SUCCEEDED):
            raise ValueError()
        if success and (not self.process_observed or not self.execution_permitted):
            raise ValueError()
        if self.status == Status.LAUNCHED and not self.process_creation_attempted:
            raise ValueError()
        if self.status == Status.ALREADY_RUNNING and self.process_creation_attempted:
            raise ValueError()
        return self


class ProcessObservation(Model):
    application_id: AppId
    identity: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)
    matched: bool
    available: bool = True


class AdapterMetadata(Model):
    adapter_id: Literal["windows.application.launch.v1"] = "windows.application.launch.v1"
    capability: Literal["application.launch"] = "application.launch"
    idempotent: Literal[False] = False
    rollback_supported: Literal[False] = False
    cancellation_supported: Literal[True] = True
    fake: Literal[False] = False
