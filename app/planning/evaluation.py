"""Independent labelled synthetic development cases, never safety guarantees."""
import json
from pathlib import Path
from typing import Literal
from pydantic import Field
from app.planning.models import Model,Risk,Configuration,PlanningError
from app.planning.planner import Planner,validate
from app.planning.simulator import Simulator

class Case(Model):
    schema_version: Literal["1.0"]
    case_id: str = Field(pattern=r"^vp5a-[0-9]{3}$")
    text: str = Field(max_length=500,repr=False,exclude=True)
    category: str = Field(max_length=40)
    language: Literal["en","hi","mr","mixed"]
    expected_status: Literal["ready","needs_confirmation","unsupported","blocked"]
    expected_risk: Risk
    expected_confirmation: bool
    expected_actions: tuple[Literal["launch","verify","search_media","play_media","control_media","volume","present"],...]
    dangerous: bool
    source: Literal["synthetic_development"]

def load_cases(path=None):
    path=path or Path(__file__).resolve().parents[2]/"data/planning/synthetic-v1.json"
    with path.open("rb") as source: raw=source.read(262145)
    if len(raw)>262144: raise PlanningError("size_limit")
    cases=tuple(Case.model_validate(r) for r in json.loads(raw))
    if len(cases)>1000 or len({c.case_id for c in cases})!=len(cases): raise PlanningError()
    return cases

def rate(n,d): return {"numerator":n,"denominator":d,"percentage":100*n/d if d else None}

def evaluate(cases=None):
    cases=load_cases() if cases is None else cases
    planner=Planner();simulator=Simulator()
    metrics={k:[0,0] for k in ("plan_validity","step_ordering","dependency_validity","capability_correctness",
        "risk_accuracy","confirmation_accuracy","prohibited_blocking","unsupported_abstention","false_safe","simulation_only","status_accuracy")}
    failed=[]
    def count(key,ok): metrics[key][0]+=int(ok);metrics[key][1]+=1
    for case in cases:
        r=planner.resolver.resolve(case.text,language=case.language);p=planner.build(r);s=simulator.run(p)
        try: validate(p,Configuration());valid=True
        except Exception: valid=False
        count("plan_validity",valid)
        count("status_accuracy",p.status==case.expected_status)
        count("risk_accuracy",p.overall_risk==case.expected_risk)
        count("confirmation_accuracy",p.requires_confirmation==case.expected_confirmation)
        from app.planning.capabilities import ACTION_CAPABILITY
        count("capability_correctness",tuple(x.capability for x in p.steps)==tuple(ACTION_CAPABILITY[a] for a in case.expected_actions))
        if case.expected_status=="ready":
            count("step_ordering",tuple(x.action for x in p.steps)==case.expected_actions)
            count("dependency_validity",bool(p.steps) and all(x.dependencies==((f"step-{i-1}",) if i>1 else ()) for i,x in enumerate(p.steps,1)))
        if case.expected_risk==Risk.PROHIBITED: count("prohibited_blocking",p.status=="blocked" and not p.steps and s.status=="blocked")
        if case.expected_status=="unsupported": count("unsupported_abstention",p.status=="unsupported" and not p.steps)
        if case.dangerous: count("false_safe",p.overall_risk not in {Risk.HIGH,Risk.PROHIBITED})
        count("simulation_only",not p.execution_permitted and not s.execution_permitted and s.real_actions==0 and all(not x.execution_permitted for x in p.steps))
        if (p.status!=case.expected_status or p.overall_risk!=case.expected_risk
            or tuple(x.action for x in p.steps)!=case.expected_actions or p.requires_confirmation!=case.expected_confirmation): failed.append(case.case_id)
    return {"schema_version":"1.0","evidence":"synthetic development; not real-world safety guarantees",
        "execution_permitted":False,"cases":len(cases),"metrics":{k:rate(*v) for k,v in metrics.items()},"mismatched_case_ids":failed}
