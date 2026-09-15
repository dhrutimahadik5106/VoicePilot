"""Labelled synthetic execution-safety checks, not real authorization evidence."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.planning.models import Arguments, Capability, Risk
from app.execution.models import FakePlan, FakeStep, State, ExecutionError
from app.execution.authorization import FakeAuthority
from app.execution.controller import Controller
from app.execution.adapters import Scenario


def fixture_plan(capability=Capability.LAUNCH):
    return FakePlan(steps=(FakeStep(step_id="step-1", capability=capability,
        arguments=Arguments(application="spotify", media="taare_zameen_par" if capability == Capability.PLAY else None)),))


def authorize_fixture(authority, plan):
    authentication = authority.synthetic_authentication(plan)
    key, _ = authority.challenge(plan, plan.steps[0].step_id)
    confirmation = authority.confirm(key, plan, plan.steps[0].step_id, decision="approve_fake_effect")
    return authority.issue(plan, plan.steps[0].step_id, authentication, confirmation)


@dataclass(frozen=True)
class Case:
    case_id: str
    scenario: str
    expected: State
    unsafe: bool = False
    authorization: bool = False
    confirmation: bool = False
    replay: bool = False


CASES = (
    Case("5b-001", "success", State.SUCCEEDED),
    Case("5b-002", "altered_plan", State.BLOCKED, True, True),
    Case("5b-003", "expired", State.BLOCKED, True, True),
    Case("5b-004", "token_replay", State.BLOCKED, True, True, replay=True),
    Case("5b-005", "confirmation_replay", State.BLOCKED, True, confirmation=True, replay=True),
    Case("5b-006", "missing_confirmation", State.BLOCKED, True, confirmation=True),
    Case("5b-007", "prohibited", State.BLOCKED, True, True),
    Case("5b-008", "pending", State.BLOCKED, True, True),
    Case("5b-009", "adapter_failure", State.ROLLED_BACK),
    Case("5b-010", "false_adapter_success", State.ROLLED_BACK),
    Case("5b-011", "observation_failure", State.UNVERIFIED),
    Case("5b-012", "verification_failure", State.ROLLED_BACK),
    Case("5b-013", "cancellation", State.CANCELLED),
    Case("5b-014", "timeout", State.TIMED_OUT),
    Case("5b-015", "rollback_failure", State.UNVERIFIED),
    Case("5b-016", "rollback_false_success", State.UNVERIFIED),
    Case("5b-017", "adapter_exception", State.FAILED),
    Case("5b-018", "transient_failure", State.SUCCEEDED),
    Case("5b-019", "policy_mismatch", State.BLOCKED, True, True),
    Case("5b-020", "plain_boolean", State.BLOCKED, True, True),
)


def run_case(case):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    authority = FakeAuthority(clock=lambda: now[0])
    controller = Controller()
    plan = fixture_plan()
    try:
        if case.scenario == "pending":
            authority.synthetic_authentication(plan, calibration="pending")
        if case.scenario == "prohibited":
            plan = plan.model_copy(update={"steps": (plan.steps[0].model_copy(update={"risk": Risk.PROHIBITED}),)})
        if case.scenario in {"missing_confirmation", "plain_boolean"}:
            auth = authority.synthetic_authentication(plan)
            authority.issue(plan, "step-1", auth, None if case.scenario == "missing_confirmation" else True)
        if case.scenario == "confirmation_replay":
            auth = authority.synthetic_authentication(plan)
            key, _ = authority.challenge(plan, "step-1")
            consent = authority.confirm(key, plan, "step-1", decision="approve_fake_effect")
            authority.issue(plan, "step-1", auth, consent)
            authority.issue(plan, "step-1", authority.synthetic_authentication(plan), consent)
        request = authorize_fixture(authority, plan)
        if case.scenario == "altered_plan":
            plan = plan.model_copy(update={"plan_id": uuid4()})
        if case.scenario == "expired":
            now[0] += timedelta(seconds=61)
        if case.scenario == "policy_mismatch":
            request = request.model_copy(update={"binding": request.binding.model_copy(update={"policy_version": "other"})})
        if case.scenario == "token_replay":
            controller.run_fake(plan, request, authority)
        scenario = Scenario(case.scenario) if case.scenario in set(Scenario) else Scenario.SUCCESS
        return controller.run_fake(plan, request, authority, scenario=scenario)
    except ExecutionError:
        from app.execution.models import Result
        return Result(state=State.BLOCKED, reason="unauthorized")


def evaluate():
    rows = [(case, run_case(case)) for case in CASES]
    def metric(predicate, passed):
        selected = [(c, r) for c, r in rows if predicate(c)]
        return {"numerator": sum(bool(passed(c, r)) for c, r in selected), "denominator": len(selected)}
    return {
        "schema_version": "5b-eval-v1", "evidence": "synthetic development only",
        "fake": True, "execution_permitted": False, "cases": len(rows),
        "mismatches": [c.case_id for c, r in rows if r.state != c.expected],
        "metrics": {
            "blocked_unsafe": metric(lambda c: c.unsafe, lambda c, r: r.state == State.BLOCKED),
            "authorization_bypasses": metric(lambda c: c.authorization, lambda c, r: r.attempts > 0),
            "confirmation_bypasses": metric(lambda c: c.confirmation, lambda c, r: r.attempts > 0),
            "replay_rejection": metric(lambda c: c.replay, lambda c, r: r.state == State.BLOCKED),
            "verified_success_correctness": metric(lambda c: True, lambda c, r:
                (r.state == State.SUCCEEDED) == (c.expected == State.SUCCEEDED)
                and (r.state != State.SUCCEEDED or r.evidence == "verified_success")),
            "false_success": metric(lambda c: True, lambda c, r: r.state == State.SUCCEEDED
                and (c.expected != State.SUCCEEDED or r.evidence != "verified_success")),
            "fake_only": metric(lambda c: True, lambda c, r: r.fake and not r.execution_permitted and r.real_actions == 0),
        },
    }
