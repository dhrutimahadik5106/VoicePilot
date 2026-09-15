"""Typed observation/verification/recovery only; no executable tool adapters."""
from typing import Protocol
from app.planning.models import Configuration, Simulation, StepResult, Step, Risk
from app.planning.planner import validate

class Executor(Protocol):
    def simulate(self, step: Step) -> str: ...
class Observer(Protocol):
    def observe(self, step: Step) -> str: ...
class Verifier(Protocol):
    def verify(self, step: Step, observation: str) -> bool: ...
class Recovery(Protocol):
    def recover(self, step: Step, attempts: int) -> str: ...

class Simulator:
    def __init__(self, configuration=None, *, _test_failures=frozenset()):
        self.configuration=configuration or Configuration()
        self._failures=frozenset(_test_failures)  # Trusted test-only injection; no CLI flag.
    def simulate(self,step): return "simulated_mismatch" if step.step_id in self._failures else "simulated_match"
    def observe(self,step): return self.simulate(step)
    def verify(self,step,observation): return observation=="simulated_match"
    def recover(self,step,attempts): return "retry_exhausted_abort"
    def run(self,plan,*,cancel=None,confirmations=None,receipt=None):
        if cancel is not None and cancel.is_set(): return Simulation(status="cancelled")
        try:
            plan=validate(plan,self.configuration)
            if plan.status!="ready": return Simulation(status=plan.status if plan.status in {"unsupported","cancelled","needs_confirmation"} else "blocked")
            if plan.overall_risk==Risk.PROHIBITED: return Simulation(status="blocked")
            if plan.requires_confirmation and (confirmations is None or not confirmations.consume(plan,receipt)):
                return Simulation(status="needs_confirmation")
            results=[];failed=False
            for step in plan.steps:
                if cancel is not None and cancel.is_set(): return Simulation(status="cancelled")
                if failed:
                    results.append(StepResult(step_id=step.step_id,status="blocked",attempts=0,observation="not_observed",recovery="dependency_aborted"));continue
                for attempt in range(1,step.max_retries+2):
                    if cancel is not None and cancel.is_set(): return Simulation(status="cancelled")
                    observation=self.observe(step);ok=self.verify(step,observation)
                    if cancel is not None and cancel.is_set(): return Simulation(status="cancelled")
                    if ok: break
                results.append(StepResult(step_id=step.step_id,status="simulated_success" if ok else "simulated_failure",
                    attempts=attempt,observation=observation,
                    recovery="none" if ok else self.recover(step,step.max_retries+1)))
                failed=not ok
            return Simulation(status="simulated_failure" if failed else "simulated_success",steps=tuple(results))
        except Exception:
            return Simulation(status="blocked")
