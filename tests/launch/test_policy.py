from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from app.launch.allowlist import ALLOWLIST, resolve_application, validate_path
from app.launch.authorization import ManualAuthority
from app.launch.models import Configuration, LaunchPlan, LaunchError, Permit, LaunchResult, Status
from app.execution.models import State
from tests.launch.helpers import IDENTITY, grant


@pytest.mark.parametrize("text,expected", [("Notepad", "notepad"), ("calc", "calculator"),
    ("Calculator", "calculator"), ("Google Chrome", "chrome"), ("spotify", "spotify")])
def test_closed_aliases(text, expected):
    assert resolve_application(text) == expected
    assert set(ALLOWLIST) == {"notepad", "calculator", "chrome", "spotify"}


@pytest.mark.parametrize("text", ["browser", "notepad chrome", "cmd", "powershell", "python", "https://example.invalid",
    "spotify:track", "%APPDATA%", "C:/app.exe", "notepad.exe", True, "PRIVATE_MARKER"])
def test_unknown_aliases(text):
    with pytest.raises(LaunchError) as error:
        resolve_application(text)
    assert "PRIVATE_MARKER" not in repr(error.value)


@pytest.mark.parametrize("path", ["notepad.exe", "C:notepad.exe", "D:/Windows/notepad.exe",
    "//server/share/notepad.exe", "C:/untrusted/notepad.exe", "C:/Windows/System32/../notepad.exe",
    "C:/Windows/System32/notepad.exe:stream", "C:/Windows/System32/notepad.exe ",
    "C:/Windows/System32/notepad.exe.", "C:/Windows/System32/notepad.cmd", "C:/Windows/System32/notepad.lnk",
    "C:/Windows/System32/notepad.ps1", "C:/Windows/System32/%PATH%/notepad.exe"])
def test_unsafe_paths(path):
    with pytest.raises(LaunchError):
        validate_path(path, "C:/Windows/System32", ("notepad.exe",))


def test_safe_fixed_path():
    assert validate_path("C:/Windows/System32/notepad.exe", "C:/Windows/System32", ("notepad.exe",)).name == "notepad.exe"


@pytest.mark.parametrize("change", [{"application_id": "cmd"}, {"application_id": ["notepad", "chrome"]},
    {"arguments": ["PRIVATE_MARKER"]}, {"path": "PRIVATE_MARKER"}, {"url": "PRIVATE_MARKER"},
    {"arguments_allowed": True}, {"elevation_allowed": True}, {"step_id": "step-2"}, {"capability": "code.execute"}])
def test_request_rejects_unapproved_inputs(change):
    with pytest.raises(Exception) as error:
        LaunchPlan(**({"application_id": "notepad", "identity": IDENTITY} | change))
    assert "PRIVATE_MARKER" not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("change", [{"maximum_applications": 2}, {"maximum_applications": True},
    {"arguments_allowed": True}, {"elevation_allowed": True}, {"discovery_timeout": 0},
    {"observation_timeout": float("nan")}, {"launch_timeout": True}, {"authorization_expiry": 61},
    {"approved_application_ids": ["cmd"]}, {"approved_application_ids": ["notepad", "notepad"]}])
def test_safe_configuration(change):
    with pytest.raises(Exception):
        Configuration(**change)


@pytest.mark.parametrize("response", [True, False, "yes", "confirmed=true", "LAUNCH chrome", "launch notepad", "no"])
def test_exact_confirmation_required(response):
    authority = ManualAuthority()
    plan = LaunchPlan(application_id="notepad", identity=IDENTITY)
    key = authority.challenge(plan, typed_application="notepad")
    with pytest.raises(LaunchError):
        authority.confirm(key, plan, response=response)
    with pytest.raises(LaunchError):
        authority.confirm(key, plan, response="LAUNCH notepad")


@pytest.mark.parametrize("change", [{"plan_id": uuid4()}, {"application_id": "chrome"}, {"identity": "2" * 64},
    {"policy_version": "changed"}, {"arguments_allowed": True}, {"authentication_id": uuid4()},
    {"mode": "authenticated_voice"}])
def test_confirmation_and_permit_bind_every_field(change):
    plan, permit, authority = grant()
    changed = plan.model_copy(update=change)
    assert not authority.consume(changed, permit)
    assert not authority.consume(plan, permit)


def test_expiry_and_replay():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    authority = ManualAuthority(clock=lambda: now[0])
    plan, permit, _ = grant(authority=authority)
    now[0] += timedelta(seconds=30)
    assert not authority.consume(plan, permit)
    plan, permit, _ = grant(authority=authority)
    assert authority.consume(plan, permit)
    assert not authority.consume(plan, permit)
    assert not ManualAuthority().consume(plan, permit)
    assert not authority.consume(plan, Permit())
    assert not authority.consume(plan, True)


def test_challenge_expiry_and_mutation():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    authority = ManualAuthority(clock=lambda: now[0])
    plan = LaunchPlan(application_id="notepad", identity=IDENTITY)
    key = authority.challenge(plan, typed_application="notepad")
    now[0] += timedelta(seconds=31)
    with pytest.raises(LaunchError):
        authority.confirm(key, plan, response="LAUNCH notepad")
    with pytest.raises(LaunchError):
        authority.challenge(plan, typed_application="Notepad")
    key = authority.challenge(plan, typed_application="notepad")
    with pytest.raises(LaunchError):
        authority.confirm(key, plan.model_copy(update={"identity": "2" * 64}), response="LAUNCH notepad")


@pytest.mark.parametrize("status", [Status.LAUNCHED, Status.ALREADY_RUNNING])
def test_success_requires_observation(status):
    with pytest.raises(Exception):
        LaunchResult(status=status, state=State.SUCCEEDED)
