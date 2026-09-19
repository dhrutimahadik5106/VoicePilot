from threading import Event
from uuid import uuid4
import pytest
from app.launch.controller import LaunchController, WindowsLaunchAdapter
from app.launch.models import Configuration, LaunchAudit, LaunchError, Status, ProcessObservation
from app.execution.models import State
from app.planning.models import Simulation
from app.execution.authorization import FakeAuthority
from tests.launch.helpers import Backend, Clock, grant, IDENTITY


@pytest.fixture
def setup(monkeypatch):
    clock = Clock()
    backend = Backend(clock)
    controller = LaunchController(backend=backend, clock=clock)
    def wait(event, duration=None):
        clock.value += duration or 0
        return event.is_set()
    monkeypatch.setattr(Event, "wait", wait)
    return backend, controller


@pytest.mark.parametrize("app", ["notepad", "calculator", "chrome", "spotify"])
def test_one_verified_launch(setup, app):
    backend, controller = setup
    result = controller.run(*grant(app))
    assert result.status == Status.LAUNCHED and result.process_observed
    assert backend.created == 1 and backend.calls == ["observe", "revalidate", "launch", "observe"]
    assert not result.foreground_verified and not result.rollback_attempted
    assert all(not event.fake for event in result.events)
    assert result.events[-1].state == State.SUCCEEDED


def test_already_running_no_process_creation(setup):
    backend, controller = setup
    backend.already = True
    result = controller.run(*grant())
    assert result.status == Status.ALREADY_RUNNING and backend.created == 0
    assert not result.process_creation_attempted and result.process_observed


@pytest.mark.parametrize("fault", ["changed", "no_observation", "false_success", "exception", "launch_error"])
def test_failures_fail_closed(setup, fault):
    backend, controller = setup
    if fault == "changed":
        backend.changed = True
    elif fault == "no_observation":
        backend.available = False
    elif fault == "false_success":
        backend.match = False
    else:
        backend.error = RuntimeError("PRIVATE_MARKER") if fault == "exception" else LaunchError(Status.LAUNCH_FAILED)
    result = controller.run(*grant())
    assert result.status not in {Status.LAUNCHED, Status.ALREADY_RUNNING}
    assert backend.created <= 1 and not result.process_observed
    assert "PRIVATE_MARKER" not in repr(result) + result.model_dump_json()
    if fault in {"changed", "no_observation"}:
        assert backend.created == 0
    if fault == "false_success":
        assert result.status == Status.VERIFICATION_FAILED


def test_independent_observer_not_adapter_claims(setup, monkeypatch):
    backend, controller = setup
    backend.match = False
    monkeypatch.setattr(WindowsLaunchAdapter, "observe", lambda *a: True)
    monkeypatch.setattr(WindowsLaunchAdapter, "verify", lambda *a: True)
    result = controller.run(*grant())
    assert result.status == Status.VERIFICATION_FAILED and backend.created == 1


def test_wrong_application_observation_blocks_before_launch(setup):
    backend, controller = setup
    backend.observe = lambda *a: ProcessObservation(application_id="chrome", identity=IDENTITY, matched=True)
    result = controller.run(*grant("notepad"))
    assert result.status == Status.OBSERVATION_UNAVAILABLE and backend.created == 0


@pytest.mark.parametrize("moment", ["before", "revalidate", "after_launch"])
def test_emergency_stop(setup, moment):
    backend, controller = setup
    if moment == "before":
        controller.emergency_stop()
    elif moment == "revalidate":
        backend.on_revalidate = controller.emergency_stop
    else:
        backend.on_launch = controller.emergency_stop
    result = controller.run(*grant())
    assert result.status == Status.EMERGENCY_STOPPED and not result.rollback_attempted
    assert backend.created == (moment == "after_launch")
    assert controller.run(*grant()).status == Status.EMERGENCY_STOPPED


def test_cancelled_before_launch(setup):
    backend, controller = setup
    cancel = Event()
    cancel.set()
    assert controller.run(*grant(), cancel=cancel).status == Status.CANCELLED
    assert backend.created == 0


@pytest.mark.parametrize("moment", ["revalidate", "launch"])
def test_timeout_is_not_success_or_retry(setup, moment):
    backend, controller = setup
    def delay():
        backend.clock.value += 100
    if moment == "revalidate":
        backend.on_revalidate = delay
    else:
        backend.on_launch = delay
    result = controller.run(*grant())
    assert result.status == Status.TIMED_OUT and not result.process_observed
    assert backend.created == (moment == "launch")


def test_replay_and_fake_authorization_blocked(setup):
    backend, controller = setup
    request = grant()
    assert controller.run(*request).status == Status.LAUNCHED
    assert controller.run(*request).status == Status.INVALID_AUTHORIZATION
    assert controller.run(request[0], True, request[2]).status == Status.INVALID_AUTHORIZATION
    assert controller.run(request[0], request[1], FakeAuthority()).status == Status.INVALID_AUTHORIZATION
    assert controller.run(Simulation(status="simulated_success"), True, FakeAuthority()).state == State.BLOCKED
    assert backend.created == 1


@pytest.mark.parametrize("setting", ["windows_adapter_enabled", "manual_launch_testing_enabled"])
def test_disabled_policy(setting):
    backend = Backend()
    controller = LaunchController(Configuration(**{setting: False}), backend=backend)
    assert controller.run(*grant()).status == Status.DISABLED
    assert backend.created == 0


@pytest.mark.parametrize("field", ["transcript", "entity", "path", "embedding", "profile", "similarity", "credential"])
def test_audit_rejects_private_fields(field):
    with pytest.raises(Exception) as error:
        LaunchAudit(previous=State.CREATED, state=State.BLOCKED, reason=Status.ACCESS_DENIED, **{field: "PRIVATE_MARKER"})
    assert "PRIVATE_MARKER" not in str(error.value) + repr(error.value)


def test_audit_omits_identity_and_application(setup):
    backend, controller = setup
    plan, permit, authority = grant()
    result = controller.run(plan, permit, authority)
    text = "".join(event.model_dump_json() + repr(event) for event in result.events)
    for value in ("notepad", IDENTITY, str(permit.handle), "path", "profile"):
        assert value not in text


def test_interrupt_after_creation_reports_attempt(setup):
    backend, controller = setup
    backend.error = KeyboardInterrupt()
    result = controller.run(*grant())
    assert result.status == Status.CANCELLED
    assert result.process_creation_attempted and backend.created == 1
    assert not result.process_observed and not result.rollback_attempted


def test_clock_failure_releases_admission_lock(setup):
    backend, controller = setup
    def broken_clock():
        raise ValueError("PRIVATE_MARKER")
    controller.clock = broken_clock
    result = controller.run(*grant())
    assert "PRIVATE_MARKER" not in result.model_dump_json()
    controller.clock = backend.clock
    assert controller.run(*grant()).status == Status.LAUNCHED


@pytest.mark.parametrize("moment", ["revalidate", "launch"])
def test_individual_stage_budget(setup, moment):
    backend, controller = setup
    def delay():
        backend.clock.value += 5.1
    if moment == "revalidate":
        backend.on_revalidate = delay
    else:
        backend.on_launch = delay
    result = controller.run(*grant())
    assert result.status == Status.TIMED_OUT
    assert backend.created == (moment == "launch")
