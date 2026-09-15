from threading import Event
import json
import pytest
from app.execution.adapters import FakeAdapter, IndependentObserver, Scenario
from app.execution.authorization import FakeAuthority
from app.execution.controller import Controller
from app.execution.evaluation import CASES, evaluate, fixture_plan, authorize_fixture, run_case
from app.execution.models import AuditEvent, Configuration, Result, State
from app.execution.registry import REGISTRY, validate_plan
from app.execution.state import Machine
from app.planning.models import Capability, Simulation


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_labelled_scenarios(case):
    result = run_case(case)
    assert result.state == case.expected
    assert result.fake and not result.execution_permitted and result.real_actions == 0


@pytest.mark.parametrize("capability", [c for c in Capability if c not in REGISTRY])
def test_closed_registry(capability):
    plan = fixture_plan().model_copy(update={"steps": (fixture_plan().steps[0].model_copy(update={"capability": capability}),)})
    with pytest.raises(Exception):
        validate_plan(plan)
    with pytest.raises(KeyError):
        REGISTRY[capability]


def test_unknown_adapter_and_registry_immutable():
    with pytest.raises(KeyError):
        REGISTRY["module.private.Adapter"]
    with pytest.raises(TypeError):
        REGISTRY[Capability.LAUNCH] = None


def test_production_disabled_and_diagnostics_rejected():
    controller = Controller()
    assert controller.run(authenticated=True, confirmed=True).reason == "disabled"
    for untrusted in (True, {}, Simulation(status="simulated_success")):
        assert controller.run_fake(untrusted, True, FakeAuthority()).state == State.BLOCKED


@pytest.mark.parametrize("capability,retries,attempts", [
    (Capability.LAUNCH, 0, 1), (Capability.LAUNCH, 1, 2), (Capability.LAUNCH, 2, 3),
    (Capability.LAUNCH, 3, 4), (Capability.PLAY, 3, 1),
])
def test_retry_limits_and_non_idempotent(capability, retries, attempts):
    authority = FakeAuthority()
    plan = fixture_plan(capability)
    result = Controller(Configuration(max_retries=retries)).run_fake(
        plan, authorize_fixture(authority, plan), authority, scenario=Scenario.FAIL)
    assert result.attempts == attempts and result.state != State.SUCCEEDED


def test_idempotency_survives_new_nonce():
    plan = fixture_plan()
    authority = FakeAuthority()
    controller = Controller()
    assert controller.run_fake(plan, authorize_fixture(authority, plan), authority).state == State.SUCCEEDED
    duplicate = controller.run_fake(plan, authorize_fixture(authority, plan), authority)
    assert duplicate.state == State.BLOCKED and duplicate.attempts == 0


@pytest.mark.parametrize("scenario", [Scenario.FALSE_SUCCESS, Scenario.NO_OBSERVATION,
                                      Scenario.WRONG_EFFECT, Scenario.ROLLBACK_FAIL, Scenario.ROLLBACK_LIE])
def test_independent_observation_not_adapter_claim(scenario, monkeypatch):
    def lie(*args):
        pytest.fail("adapter observation/verification must not be trusted")
    monkeypatch.setattr(FakeAdapter, "observe", lie)
    monkeypatch.setattr(FakeAdapter, "verify", lie)
    authority = FakeAuthority()
    plan = fixture_plan()
    result = Controller().run_fake(plan, authorize_fixture(authority, plan), authority, scenario=scenario)
    assert result.state != State.SUCCEEDED
    if scenario in {Scenario.ROLLBACK_FAIL, Scenario.ROLLBACK_LIE, Scenario.NO_OBSERVATION}:
        assert result.state == State.UNVERIFIED and not result.rollback_observed


def test_success_has_complete_validated_transitions():
    plan = fixture_plan()
    authority = FakeAuthority()
    result = Controller().run_fake(plan, authorize_fixture(authority, plan), authority)
    assert [e.state for e in result.events] == [State.VALIDATING, State.AWAITING, State.AUTHORIZED,
        State.RUNNING, State.OBSERVING, State.VERIFYING, State.SUCCEEDED]
    assert result.evidence == "verified_success"


@pytest.mark.parametrize("state", [State.RUNNING, State.SUCCEEDED, State.ROLLED_BACK, State.AUTHORIZED])
def test_invalid_transitions(state):
    with pytest.raises(Exception):
        Machine().move(state)


@pytest.mark.parametrize("change", [{"state": State.SUCCEEDED}, {"state": State.ROLLED_BACK},
                                     {"execution_permitted": True}, {"real_actions": 1}])
def test_result_cannot_claim_unverified_success(change):
    with pytest.raises(Exception):
        Result(**({"state": State.BLOCKED, "reason": "ok"} | change))


def test_cancel_before_adapter():
    event = Event()
    event.set()
    plan = fixture_plan()
    authority = FakeAuthority()
    result = Controller().run_fake(plan, authorize_fixture(authority, plan), authority, cancel=event)
    assert result.state == State.CANCELLED and result.attempts == 0


def test_emergency_stop_active_and_latched(monkeypatch):
    controller = Controller()
    plan = fixture_plan()
    authority = FakeAuthority()
    seen = []
    def stop(adapter, key, step, cancel):
        controller.emergency_stop()
        seen.append(cancel.is_set())
        return True
    monkeypatch.setattr(FakeAdapter, "execute", stop)
    result = controller.run_fake(plan, authorize_fixture(authority, plan), authority)
    assert result.state == State.CANCELLED and result.reason == "emergency_stop" and seen == [True]
    assert controller.run_fake(plan, authorize_fixture(authority, plan), authority).reason == "emergency_stop"


def test_timeout_after_observation(monkeypatch):
    now = [0.0]
    original = IndependentObserver.observe
    calls = []
    def observe(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            now[0] = 6.0
        return original(self, *args, **kwargs)
    monkeypatch.setattr(IndependentObserver, "observe", observe)
    plan = fixture_plan()
    authority = FakeAuthority()
    result = Controller(clock=lambda: now[0]).run_fake(plan, authorize_fixture(authority, plan), authority)
    assert result.state == State.TIMED_OUT and not result.rollback_observed


@pytest.mark.parametrize("method", ["execute", "rollback"])
def test_arbitrary_exception_private(method, monkeypatch):
    def fail(*args):
        raise RuntimeError("PRIVATE_MARKER")
    monkeypatch.setattr(FakeAdapter, method, fail)
    plan = fixture_plan()
    authority = FakeAuthority()
    result = Controller().run_fake(plan, authorize_fixture(authority, plan), authority,
                                   scenario=Scenario.WRONG_EFFECT if method == "rollback" else Scenario.SUCCESS)
    assert result.state != State.SUCCEEDED
    assert "PRIVATE_MARKER" not in repr(result) + result.model_dump_json()


@pytest.mark.parametrize("field", ["transcript", "audio", "embedding", "profile", "similarity", "path", "arguments"])
def test_audit_forbids_private_fields(field):
    with pytest.raises(Exception) as error:
        AuditEvent(previous=State.CREATED, state=State.BLOCKED, reason="ok", **{field: "PRIVATE_MARKER"})
    assert "PRIVATE_MARKER" not in repr(error.value) + str(error.value)


def test_audit_omits_entity_and_evidence_material():
    plan = fixture_plan()
    authority = FakeAuthority()
    request = authorize_fixture(authority, plan)
    result = Controller().run_fake(plan, request, authority)
    text = result.model_dump_json() + repr(result)
    for forbidden in ("spotify", "taare", request.binding.plan_digest, str(request.binding.nonce),
                      str(request.binding.authentication_id), "similarity", "transcript"):
        assert forbidden not in text


def test_evaluation_and_cli():
    from app.execution.cli import main
    report = evaluate()
    assert report["cases"] == 20 and report["mismatches"] == []
    assert report["metrics"]["false_success"] == {"numerator": 0, "denominator": 20}
    for command in ("status", "registry", "evaluate"):
        output = []
        assert main([command], write=output.append) == 0
        assert json.loads(output[0])["execution_permitted"] is False
    output = []
    assert main(["PRIVATE_MARKER"], write=output.append) == 2
    assert "PRIVATE_MARKER" not in str(output)


def test_idempotency_across_controllers():
    plan = fixture_plan(Capability.PLAY)
    authority = FakeAuthority()
    first = authorize_fixture(authority, plan)
    second = authorize_fixture(authority, plan)
    assert Controller().run_fake(plan, first, authority).state == State.SUCCEEDED
    result = Controller().run_fake(plan, second, authority)
    assert result.state == State.BLOCKED and result.attempts == 0


def test_concurrent_admission_rejected(monkeypatch):
    controller = Controller()
    authority = FakeAuthority()
    plan = fixture_plan()
    request = authorize_fixture(authority, plan)
    nested = []
    original = FakeAdapter.execute
    def execute(adapter, *args):
        nested.append(controller.run_fake(plan, request, authority))
        return original(adapter, *args)
    monkeypatch.setattr(FakeAdapter, "execute", execute)
    assert controller.run_fake(plan, request, authority).state == State.SUCCEEDED
    assert nested[0].state == State.BLOCKED and nested[0].attempts == 0


def test_existing_diagnostic_plan_is_not_execution_authority():
    from uuid import uuid4
    from app.planning.models import Plan, Risk
    plan = Plan(trace_id=uuid4(), status="blocked", overall_risk=Risk.PROHIBITED,
                requires_confirmation=True, authentication="unauthenticated_diagnostic")
    assert Controller().run_fake(plan, True, FakeAuthority()).state == State.BLOCKED
    with pytest.raises(Exception):
        FakeAuthority().synthetic_authentication(plan)
