"""Validated resolver output to fixed templates; no text-to-code path."""
from uuid import uuid4
from app.commands.models import Resolution, render_command
from app.commands.resolver import CommandResolver
from app.planning.models import Plan, Step, Arguments, Configuration, Risk, PlanningError
from app.planning.capabilities import ACTION_CAPABILITY, REGISTRY
from app.planning.risk import input_risk


def validate(plan, config):
    plan=Plan.model_validate(plan.model_dump() | {"objective":plan.objective})
    if len(plan.steps)>config.max_steps: raise PlanningError()
    depths={}
    for s in plan.steps:
        depths[s.step_id]=1+max((depths[d] for d in s.dependencies),default=0)
        if depths[s.step_id]>config.max_depth or s.max_retries>config.max_retries or s.timeout>config.step_timeout: raise PlanningError()
    if sum(s.timeout*(s.max_retries+1) for s in plan.steps)>config.total_timeout: raise PlanningError()
    return plan

class Planner:
    def __init__(self, configuration=None, *, resolver=None, risk_engine=input_risk):
        self.configuration=configuration or Configuration()
        self.resolver=resolver or CommandResolver.from_directory()
        self.risk_engine=risk_engine

    def build_basic(self, text):
        """Return a typed non-executing Phase 6B plan; no authorization is issued."""
        from app.commands.basic import resolve_basic
        return resolve_basic(text)

    def build(self, resolution, *, trace_id=None, authentication="unauthenticated_diagnostic"):
        trace_id=trace_id or uuid4()
        def stop(status,reason,risk=Risk.PROHIBITED):
            return Plan(trace_id=trace_id,status=status,overall_risk=risk,requires_confirmation=True,
                authentication=authentication,reasons=(reason,))
        try:
            if not self.configuration.enabled: return stop("blocked","planner_disabled")
            if not isinstance(resolution,Resolution): return stop("blocked","invalid_resolution")
            r=Resolution.model_validate(resolution.model_dump())
            # Existing Resolution schema is permissive: also check resolver semantics.
            expected=self.resolver.resolve(r.raw_transcript,language=r.language)
            if r.model_dump()!=expected.model_dump(): return stop("blocked","invalid_resolution")
            risk=self.risk_engine(r)
            if not isinstance(risk,Risk): raise PlanningError()
            if risk in {Risk.PROHIBITED,Risk.HIGH}: return stop("blocked","risk_blocked",risk)
            if r.status!="resolved" or r.requires_confirmation:
                return stop("needs_confirmation" if r.status=="needs_confirmation" else "unsupported","unresolved_command",risk)
            if r.intent is None or r.canonical_command!=render_command(r.intent,r.entities): return stop("blocked","invalid_resolution")
            registry={(e.kind,e.canonical_name):e.entity_id for e in self.resolver.aliases.entities}
            items=[]
            intent=r.intent.value
            def add(action,target,observation,**args): items.append((action,target,observation,args))
            if intent=="open_application":
                app=registry[("application",r.entities["application"])]
                add("launch","application","application_visible",application=app)
                add("verify","response","application_visible")
            elif intent=="play_media":
                if r.entities.get("application","Spotify")!="Spotify": return stop("unsupported","unsupported_application",Risk.MODERATE)
                media=registry[("media",r.entities["media"])]
                add("launch","application","application_visible",application="spotify")
                add("search_media","media","media_candidates",application="spotify",media=media)
                add("play_media","media","playback_state",application="spotify",media=media)
                add("verify","response","playback_state")
            elif intent in {"pause","resume","stop","next","previous"}:
                add("control_media","media","playback_state",control=intent)
                add("verify","response","playback_state")
            elif intent in {"volume_up","volume_down","mute","unmute"}:
                add("volume","audio","volume_state",control=intent)
                add("verify","response","volume_state")
            elif intent=="help": add("present","response","help_visible")
            else: return stop("unsupported","unsupported_intent",Risk.MODERATE)
            steps=[]
            for i,(action,target,observation,args) in enumerate(items,1):
                cap=ACTION_CAPABILITY[action]; level=REGISTRY[cap].risk
                steps.append(Step(step_id=f"step-{i}",order=i,action=action,target=target,arguments=Arguments(**args),
                    dependencies=(f"step-{i-1}",) if i>1 else (),capability=cap,risk=level,
                    requires_confirmation=level in {Risk.MODERATE,Risk.HIGH,Risk.PROHIBITED},
                    timeout=self.configuration.step_timeout,max_retries=self.configuration.max_retries,
                    expected_observation=observation))
            plan=Plan(trace_id=trace_id,status="ready",objective=r.canonical_command,source=r,
                authentication=authentication,overall_risk=max((s.risk for s in steps),key=list(Risk).index),
                requires_confirmation=any(s.requires_confirmation for s in steps),steps=tuple(steps),reasons=("fixed_template",))
            validate(plan,self.configuration)
            return plan
        except Exception:
            return stop("blocked","planning_failed")
