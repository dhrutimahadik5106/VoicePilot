from threading import Event
import pytest
from app.planning.planner import Planner
from app.planning.simulator import Simulator
from app.planning.models import Configuration

def plan(text="open Spotify"):
    p=Planner();return p.build(p.resolver.resolve(text))

def test_success_no_side_effect():
    result=Simulator().run(plan())
    assert result.status=="simulated_success" and result.real_actions==0
    assert all(not r.side_effect_occurred and r.attempts==1 for r in result.steps)

@pytest.mark.parametrize("retries",[0,1,2,3])
def test_retry_and_abort(retries):
    cfg=Configuration(max_retries=retries);p=Planner(cfg);p=p.build(p.resolver.resolve("open Spotify"))
    simulator=Simulator(cfg,_test_failures={"step-1"});calls=[]
    original=simulator.observe
    def observe(step): calls.append(step.step_id);return original(step)
    simulator.observe=observe
    result=simulator.run(p)
    assert result.status=="simulated_failure" and calls==["step-1"]*(retries+1)
    assert result.steps[0].attempts==retries+1 and result.steps[0].recovery=="retry_exhausted_abort"
    assert result.steps[1].status=="blocked" and result.steps[1].attempts==0

@pytest.mark.parametrize("stage",["before","observation","verification"])
def test_cancellation(stage):
    event=Event();simulator=Simulator()
    if stage=="before":event.set()
    if stage=="observation":
        def observe(step): event.set();return "simulated_match"
        simulator.observe=observe
    if stage=="verification":
        def verify(step,observation):event.set();return True
        simulator.verify=verify
    result=simulator.run(plan("help"),cancel=event)
    assert result.status=="cancelled" and not result.steps

def test_tampered_nonexecuting_plan():
    p=plan().model_copy(update={"execution_permitted":True})
    assert Simulator().run(p).status=="blocked"

def test_unresolved_not_simulated():
    assert Simulator().run(plan("open Spotfy")).status=="needs_confirmation"
    assert Simulator().run(plan("search cafes")).status=="unsupported"
    assert Simulator().run(plan("execute shell")).status=="blocked"

def test_observer_error_is_safe():
    s=Simulator()
    def fail(step):raise RuntimeError("PRIVATE_MARKER")
    s.observe=fail
    r=s.run(plan())
    assert r.status=="blocked" and "PRIVATE_MARKER" not in repr(r)+r.model_dump_json()
