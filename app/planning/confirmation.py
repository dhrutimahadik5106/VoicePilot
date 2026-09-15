"""In-memory, expiring single-use simulation consent, never execution authority."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from typing import Literal
from uuid import UUID,uuid4
from pydantic import Field
from app.planning.models import Model, PlanningError, Risk, Step

class Request(Model):
    confirmation_id: UUID
    plan_id: UUID
    planner_version: Literal["5a-v1"]
    step_ids: tuple[str,...]
    proposed_steps: tuple[Step,...]
    summary: Literal["Simulate the exact proposed steps"] = "Simulate the exact proposed steps"
    proposed_side_effect: Literal["None: simulation only"] = "None: simulation only"
    risk_reason: Risk
    expires_at: datetime
    status: Literal["pending","accepted","declined","cancelled","expired","consumed"] = "pending"
    execution_permitted: Literal[False] = False

class Receipt(Model):
    token: UUID = Field(repr=False,exclude=True)

def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan.model_dump(mode="json")|{"objective":plan.objective},sort_keys=True).encode()).hexdigest()

class Confirmations:
    def __init__(self, expiry=120, *, clock=lambda:datetime.now(timezone.utc)):
        if type(expiry) is not int or not 1<=expiry<=600: raise PlanningError()
        self.expiry,self.clock=expiry,clock
        self._requests={};self._receipts={}
    def request(self,plan):
        if plan.status!="ready" or plan.overall_risk==Risk.PROHIBITED: raise PlanningError("invalid_confirmation")
        key=uuid4()
        r=Request(confirmation_id=key,plan_id=plan.plan_id,planner_version=plan.planner_version,
            step_ids=tuple(s.step_id for s in plan.steps),proposed_steps=plan.steps,risk_reason=plan.overall_risk,
            expires_at=self.clock()+timedelta(seconds=self.expiry))
        self._requests[key]=(r,fingerprint(plan))
        return r
    def decide(self,key,plan,decision):
        if decision not in {"accepted","declined","cancelled"}: raise PlanningError("invalid_confirmation")
        if key not in self._requests: raise PlanningError("invalid_confirmation")
        r,binding=self._requests[key]
        if r.status!="pending" or binding!=fingerprint(plan): raise PlanningError("invalid_confirmation")
        if self.clock()>=r.expires_at:
            self._requests[key]=(r.model_copy(update={"status":"expired"}),binding)
            raise PlanningError("expired")
        self._requests[key]=(r.model_copy(update={"status":decision}),binding)
        if decision!="accepted": return None
        token=uuid4();self._receipts[token]=key
        return Receipt(token=token)
    def consume(self,plan,receipt):
        if not isinstance(receipt,Receipt) or receipt.token not in self._receipts: return False
        key=self._receipts.pop(receipt.token)
        r,binding=self._requests[key]
        valid=(r.status=="accepted" and self.clock()<r.expires_at and binding==fingerprint(plan)
               and plan.overall_risk!=Risk.PROHIBITED and plan.status=="ready")
        self._requests[key]=(r.model_copy(update={"status":"consumed" if valid else "expired"}),binding)
        return valid
