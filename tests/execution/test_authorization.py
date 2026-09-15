from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from app.execution.authorization import FakeAuthority
from app.execution.evaluation import fixture_plan, authorize_fixture
from app.execution.models import Configuration, ExecutionError, Authentication, Confirmation, Request
from app.planning.models import Arguments, Capability, Risk


@pytest.mark.parametrize("change", [
    {"enabled": True}, {"fake_only": False}, {"timeout_seconds": 0}, {"timeout_seconds": True},
    {"timeout_seconds": float("nan")}, {"max_retries": 4}, {"max_retries": True},
    {"evidence_ttl": 0}, {"max_entries": 0}, {"policy_version": "private"},
])
def test_configuration(change):
    with pytest.raises(Exception):
        Configuration(**change)


@pytest.mark.parametrize("arguments", [
    {"application": "PRIVATE_MARKER"}, {"path": "PRIVATE_MARKER"}, {"url": "https://example.invalid"},
    {"shell": "PRIVATE_MARKER"}, {"callable": lambda: None},
])
def test_argument_schema(arguments):
    with pytest.raises(Exception) as error:
        Arguments(**arguments)
    assert "PRIVATE_MARKER" not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("mutation", ["plan_id", "version", "origin", "step_id", "arguments", "risk", "capability", "condition"])
def test_exact_plan_binding(mutation):
    authority = FakeAuthority()
    plan = fixture_plan()
    request = authorize_fixture(authority, plan)
    step = plan.steps[0]
    if mutation in {"plan_id", "version", "origin"}:
        changed = plan.model_copy(update={mutation: uuid4() if mutation == "plan_id" else "altered"})
    else:
        updates = {"step_id": "step-2", "arguments": Arguments(application="chrome"),
                   "risk": Risk.PROHIBITED, "capability": Capability.DELETE,
                   "condition": "untrusted"}
        field = "expected_condition" if mutation == "condition" else mutation
        changed = plan.model_copy(update={"steps": (step.model_copy(update={field: updates[mutation]}),)})
    assert not authority.consume(changed, request)
    assert not authority.consume(plan, request)


@pytest.mark.parametrize("field", ["plan_id", "plan_digest", "step_id", "step_digest", "capability",
                                   "arguments", "authentication_id", "confirmation_id", "policy_version",
                                   "expires_at", "nonce", "fake", "execution_permitted"])
def test_request_binding_mutation(field):
    authority = FakeAuthority()
    plan = fixture_plan()
    request = authorize_fixture(authority, plan)
    values = {"plan_id": uuid4(), "plan_digest": "0" * 64, "step_id": "step-2",
              "step_digest": "0" * 64, "capability": Capability.PLAY,
              "arguments": Arguments(application="chrome"), "authentication_id": uuid4(),
              "confirmation_id": uuid4(), "policy_version": "other",
              "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc), "nonce": uuid4(),
              "fake": False, "execution_permitted": True}
    altered = request.model_copy(update={"binding": request.binding.model_copy(update={field: values[field]})})
    assert not authority.consume(plan, altered)
    assert not authority.consume(plan, request)


def test_expiry_and_replay():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    authority = FakeAuthority(clock=lambda: now[0])
    plan = fixture_plan()
    request = authorize_fixture(authority, plan)
    now[0] += timedelta(seconds=60)
    assert not authority.consume(plan, request)
    request = authorize_fixture(authority, plan)
    assert authority.consume(plan, request)
    assert not authority.consume(plan, request)
    assert not FakeAuthority().consume(plan, request)


@pytest.mark.parametrize("status,calibration", [(True, "validated"), ("verified", True),
    ("verified", "pending"), ("rejected", "validated"), ("uncertain", "validated"),
    ("unavailable", "validated"), ("cancelled", "validated")])
def test_pending_or_failed_auth(status, calibration):
    with pytest.raises(ExecutionError):
        FakeAuthority().synthetic_authentication(fixture_plan(), status=status, calibration=calibration)


@pytest.mark.parametrize("decision", [True, False, "yes", "accepted", "declined", "cancelled"])
def test_explicit_confirmation_only(decision):
    authority = FakeAuthority()
    plan = fixture_plan()
    key, review = authority.challenge(plan, "step-1")
    assert review["step"]["arguments"]["application"] == "spotify"
    with pytest.raises(ExecutionError):
        authority.confirm(key, plan, "step-1", decision=decision)
    with pytest.raises(ExecutionError):
        authority.confirm(key, plan, "step-1", decision="approve_fake_effect")


def test_confirmation_nontransferable_expiring_single_use():
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    authority = FakeAuthority(clock=lambda: now[0])
    plan = fixture_plan()
    auth = authority.synthetic_authentication(plan)
    key, _ = authority.challenge(plan, "step-1")
    now[0] += timedelta(seconds=61)
    with pytest.raises(ExecutionError):
        authority.confirm(key, plan, "step-1", decision="approve_fake_effect")
    key, _ = authority.challenge(plan, "step-1")
    with pytest.raises(ExecutionError):
        authority.confirm(key, fixture_plan(), "step-1", decision="approve_fake_effect")
    auth = authority.synthetic_authentication(plan)
    key, _ = authority.challenge(plan, "step-1")
    consent = authority.confirm(key, plan, "step-1", decision="approve_fake_effect")
    authority.issue(plan, "step-1", auth, consent)
    with pytest.raises(ExecutionError):
        authority.issue(plan, "step-1", authority.synthetic_authentication(plan), consent)


@pytest.mark.parametrize("auth,consent", [(True, True), (Authentication(), Confirmation()), (None, None)])
def test_unissued_evidence(auth, consent):
    with pytest.raises(ExecutionError):
        FakeAuthority().issue(fixture_plan(), "step-1", auth, consent)


def test_opaque_request_serialization():
    authority = FakeAuthority()
    request = authorize_fixture(authority, fixture_plan())
    text = request.model_dump_json() + repr(request) + str(request.binding) + request.binding.model_dump_json()
    for value in (str(request.authorization.handle), request.binding.plan_digest,
                  request.binding.step_digest, str(request.binding.authentication_id), "spotify"):
        assert value not in text


def test_bounded_evidence_store():
    authority = FakeAuthority(Configuration(max_entries=1))
    authority.synthetic_authentication(fixture_plan())
    with pytest.raises(ExecutionError):
        authority.synthetic_authentication(fixture_plan())
