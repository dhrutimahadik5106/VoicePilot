from datetime import datetime
from uuid import uuid4
import pytest
from app.planning.models import Configuration,Plan,Step,Arguments,PlanningError
from app.planning.planner import Planner,validate
from app.planning.capabilities import REGISTRY,CapabilitySpec

@pytest.fixture
def plan():
    p=Planner()
    return p.build(p.resolver.resolve("play Taare Zameen Par"))

@pytest.mark.parametrize("field,value",[("max_steps",0),("max_steps",True),("max_depth",0),("max_retries",4),
    ("max_retries",-1),("step_timeout",0),("step_timeout",float("nan")),("step_timeout",True),
    ("total_timeout",float("inf")),("total_timeout",1),("confirmation_expiry",0),
    ("max_audio_duration",121),("max_trace_bytes",0),("session_limit",0),("simulation_only",False),
    ("trace_root","relative/path")])
def test_bad_configuration(field,value):
    with pytest.raises(Exception): Configuration(**{field:value})

@pytest.mark.parametrize("change",[
    {"capability":"invented.tool"},{"action":"shell"},{"arguments":{"application":"powershell"}},
    {"arguments":{"url":"https://example.invalid"}},{"execution_permitted":True},
    {"timeout":float("nan")},{"timeout":0},{"max_retries":-1},{"max_retries":True}])
def test_step_schema(plan,change):
    with pytest.raises(Exception): Step(**(plan.steps[0].model_dump()|change))

@pytest.mark.parametrize("change",[
    {"capability":"media.play"},{"expected_observation":"help_visible"},
    {"risk":"informational"},{"requires_confirmation":True},{"target":"response"},
    {"dependencies":("step-2",)},{"dependencies":("step-1",)},
    {"dependencies":("unknown",)},{"order":2},{"step_id":"step-9"}])
def test_semantic_tampering(plan,change):
    doc=plan.model_dump();doc["steps"][0].update(change)
    with pytest.raises(Exception): Plan(**doc)

@pytest.mark.parametrize("change",[{"max_steps":3},{"max_depth":3},{"max_retries":0},{"step_timeout":5},{"total_timeout":50}])
def test_limits(plan,change):
    with pytest.raises(Exception): validate(plan,Configuration(**change))

def test_valid_boundaries(plan):
    assert validate(plan,Configuration(max_steps=4,max_depth=4,total_timeout=80)).status=="ready"

def test_cycle(plan):
    doc=plan.model_dump();doc["steps"][0]["dependencies"]=["step-4"]
    with pytest.raises(Exception): Plan(**doc)

def test_media_identity_and_template(plan):
    doc=plan.model_dump();doc["steps"][2]["arguments"]["media"]="taare_soundtrack"
    with pytest.raises(Exception): Plan(**doc)
    doc=plan.model_dump();doc["steps"]=doc["steps"][:1]
    with pytest.raises(Exception): Plan(**doc)

def test_unknown_registry():
    with pytest.raises(KeyError): REGISTRY["unknown"]
    with pytest.raises(Exception): CapabilitySpec(capability="arbitrary",status="simulated",risk="low",external_side_effect=False,reversible=True,impact="information")
    assert all(not c.execution_permitted for c in REGISTRY.values())
    assert REGISTRY["code.execute"].status=="prohibited"

def test_private_model_errors(plan):
    with pytest.raises(Exception) as error: Arguments(application="PRIVATE_MARKER")
    assert "PRIVATE_MARKER" not in repr(error.value)+str(error.value)
    assert not hasattr(error.value,"errors")
    assert "raw_transcript" not in plan.model_dump_json()
    assert "Taare Zameen Par" not in repr(plan)


def test_dependencies_use_actual_step_ids(plan):
    document=plan.model_dump();ids=["step-9","step-4","step-7","step-2"]
    for i,step in enumerate(document["steps"]):
        step["step_id"]=ids[i];step["dependencies"]=(ids[i-1],) if i else ()
    changed=Plan(**document)
    assert validate(changed,Configuration()).status=="ready"
