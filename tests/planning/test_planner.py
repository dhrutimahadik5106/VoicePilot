from uuid import uuid4
import pytest
from app.planning.models import Configuration,Risk
from app.planning.planner import Planner
from app.planning.evaluation import load_cases,evaluate
from app.planning.simulator import Simulator

CASES=load_cases()
@pytest.mark.parametrize("case",CASES,ids=[c.case_id for c in CASES])
def test_labelled_cases(case):
    p=Planner();r=p.resolver.resolve(case.text,language=case.language);plan=p.build(r)
    assert plan.status==case.expected_status
    assert plan.overall_risk==case.expected_risk
    assert plan.requires_confirmation==case.expected_confirmation
    assert tuple(s.action for s in plan.steps)==case.expected_actions
    assert not plan.execution_permitted

@pytest.mark.parametrize("value",[None,{},"open Spotify",True])
def test_only_resolution(value): assert Planner().build(value).status=="blocked"

def test_forged_resolution():
    p=Planner();r=p.resolver.resolve("open Spotify")
    assert p.build(r.model_copy(update={"canonical_command":"Open Chrome"})).status=="blocked"

def test_risk_exception():
    def failed(r): raise RuntimeError("PRIVATE_MARKER")
    p=Planner(risk_engine=failed);plan=p.build(p.resolver.resolve("help"))
    assert plan.status=="blocked" and plan.overall_risk==Risk.PROHIBITED
    assert "PRIVATE_MARKER" not in plan.model_dump_json()

def test_deterministic_templates():
    p=Planner();r=p.resolver.resolve("play Taare Zameen Par")
    a,b=p.build(r),p.build(r)
    assert a.steps==b.steps and a.plan_id!=b.plan_id

def test_disabled():
    p=Planner(Configuration(enabled=False))
    assert p.build(p.resolver.resolve("help")).status=="blocked"

def test_evaluation():
    report=evaluate()
    assert report["cases"]==39 and report["mismatched_case_ids"]==[]
    assert report["metrics"]["false_safe"]=={"numerator":0,"denominator":10,"percentage":0.0}
    assert report["metrics"]["prohibited_blocking"]["numerator"]==8
