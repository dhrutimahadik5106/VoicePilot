from datetime import datetime,timezone,timedelta
from uuid import uuid4
import pytest
from app.planning.confirmation import Confirmations,Receipt
from app.planning.planner import Planner
from app.planning.models import PlanningError

def plan(text="help"):
    p=Planner();return p.build(p.resolver.resolve(text))

def test_bound_single_use():
    p=plan();c=Confirmations();r=c.request(p)
    receipt=c.decide(r.confirmation_id,p,"accepted")
    assert c.consume(p,receipt)
    assert not c.consume(p,receipt)
    assert not p.execution_permitted and not r.execution_permitted
    assert str(receipt.token) not in receipt.model_dump_json()+repr(receipt)

@pytest.mark.parametrize("change",[{"plan_id":uuid4()},{"planner_version":"other"},{"objective":"different"},{"steps":()}])
def test_changed_plan(change):
    p=plan();c=Confirmations();r=c.request(p)
    with pytest.raises(Exception): c.decide(r.confirmation_id,p.model_copy(update=change),"accepted")

@pytest.mark.parametrize("decision",[True,False,"confirmed","yes"])
def test_no_confirmation_boolean(decision):
    p=plan();c=Confirmations();r=c.request(p)
    with pytest.raises(Exception): c.decide(r.confirmation_id,p,decision)

@pytest.mark.parametrize("decision",["declined","cancelled"])
def test_decline_cancel(decision):
    p=plan();c=Confirmations();r=c.request(p)
    assert c.decide(r.confirmation_id,p,decision) is None
    with pytest.raises(Exception): c.decide(r.confirmation_id,p,"accepted")

def test_expiry_and_replay():
    now=[datetime(2026,1,1,tzinfo=timezone.utc)];p=plan();c=Confirmations(1,clock=lambda:now[0]);r=c.request(p)
    now[0]+=timedelta(seconds=1)
    with pytest.raises(PlanningError,match="expired"): c.decide(r.confirmation_id,p,"accepted")
    r=c.request(p);receipt=c.decide(r.confirmation_id,p,"accepted")
    now[0]+=timedelta(seconds=1)
    assert not c.consume(p,receipt)

def test_prohibited_never_approved():
    c=Confirmations();p=plan("delete a file")
    with pytest.raises(Exception): c.request(p)
    assert not c.consume(p,Receipt(token=uuid4()))
    assert not c.consume(p,True)
