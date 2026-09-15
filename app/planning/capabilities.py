"""Closed data-only capabilities. No handlers, imports, URLs or executable payloads."""
from types import MappingProxyType
from typing import Literal
from app.planning.models import Model, Capability as C, Risk, PlanningError

class CapabilitySpec(Model):
    capability: C
    version: Literal["1.0"] = "1.0"
    status: Literal["simulated","unavailable","prohibited"]
    risk: Risk
    external_side_effect: bool
    reversible: bool
    impact: Literal["information","application","media","communication","financial","file","system","credentials","code"]
    execution_permitted: Literal[False] = False

REGISTRY = MappingProxyType({c:CapabilitySpec(capability=c,status=status,risk=risk,
    external_side_effect=side,reversible=rev,impact=impact) for c,status,risk,side,rev,impact in (
    (C.LAUNCH,"simulated",Risk.LOW,True,True,"application"),
    (C.SEARCH,"unavailable",Risk.MODERATE,True,True,"information"),
    (C.READ,"unavailable",Risk.MODERATE,False,True,"information"),
    (C.COMPARE,"unavailable",Risk.INFORMATIONAL,False,True,"information"),
    (C.MEDIA_SEARCH,"simulated",Risk.LOW,True,True,"media"),
    (C.PLAY,"simulated",Risk.LOW,True,True,"media"),
    (C.CONTROL,"simulated",Risk.LOW,True,True,"media"),
    (C.VOLUME,"simulated",Risk.LOW,True,True,"media"),
    (C.PRESENT,"simulated",Risk.INFORMATIONAL,False,True,"information"),
    (C.MESSAGE,"unavailable",Risk.HIGH,True,False,"communication"),
    (C.PAYMENT,"prohibited",Risk.PROHIBITED,True,False,"financial"),
    (C.DELETE,"prohibited",Risk.PROHIBITED,True,False,"file"),
    (C.SETTINGS,"prohibited",Risk.PROHIBITED,True,False,"system"),
    (C.CREDENTIALS,"prohibited",Risk.PROHIBITED,True,False,"credentials"),
    (C.SHELL,"prohibited",Risk.PROHIBITED,True,False,"code"))})

ACTION_CAPABILITY={"launch":C.LAUNCH,"search_media":C.MEDIA_SEARCH,"play_media":C.PLAY,
    "control_media":C.CONTROL,"volume":C.VOLUME,"present":C.PRESENT,"verify":C.PRESENT}

def assess_step(step):
    if ACTION_CAPABILITY.get(step.action)!=step.capability: raise PlanningError()
    spec=REGISTRY[step.capability]
    if spec.status!="simulated": raise PlanningError()
    a=step.arguments
    if step.action=="launch" and (a.application is None or a.media or a.control or step.target!="application"): raise PlanningError()
    if step.action in {"search_media","play_media"} and (not a.media or a.application!="spotify" or a.control or step.target!="media"): raise PlanningError()
    if step.action=="control_media" and (a.control not in {"pause","resume","stop","next","previous"} or a.media or a.application or step.target!="media"): raise PlanningError()
    if step.action=="volume" and (a.control not in {"volume_up","volume_down","mute","unmute"} or a.media or a.application or step.target!="audio"): raise PlanningError()
    if step.action in {"present","verify"} and (a.application or a.media or a.control or step.target!="response"): raise PlanningError()
    observations={"launch":"application_visible","search_media":"media_candidates","play_media":"playback_state",
                  "control_media":"playback_state","volume":"volume_state","present":"help_visible"}
    if step.action!="verify" and step.expected_observation!=observations[step.action]: raise PlanningError()
    return spec.risk
