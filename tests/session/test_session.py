"""Full transition matrix and synthetic session lifecycle."""
import json
from uuid import uuid4
import pytest
from app.session.models import State, SessionError, Configuration, View
from app.session.state import TRANSITIONS, TERMINAL, transition
from app.session.evaluation import evaluate
from app.session.service import SessionService
from app.execution.cancellation import CancellationHub
from app.session.demo import DemoDriver
from app.owner.models import OwnerError


@pytest.mark.parametrize("source",list(State))
@pytest.mark.parametrize("target",list(State))
def test_complete_transition_matrix(source,target):
    if target in TRANSITIONS[source]: assert transition(source,target) == target
    else:
        with pytest.raises(SessionError): transition(source,target)
    if source in TERMINAL: assert not TRANSITIONS[source]


def pending(service,scenario="calculator_confirm",show=False):
    view = service.create(scenario,show)
    service.action(view.session_id,"activate")
    return service.action(view.session_id,"stop_capture")


def test_all_ten_demo_scenarios():
    result = evaluate()
    assert result["correct"] == {"numerator":10,"denominator":10}
    assert result["real_actions"] == 0 and result["execution_permitted"] is False
    assert all(row["history_entries"] == 1 for row in result["cases"])


def test_capture_is_explicit_and_waveform_transient(service,monkeypatch):
    calls = []
    original = DemoDriver.__init__
    def created(self,*args): calls.append(True); original(self,*args)
    monkeypatch.setattr(DemoDriver,"__init__",created)
    view = service.create("read_volume")
    assert calls == [] and view.waveform == () and not view.listening
    with pytest.raises(SessionError): service.action(view.session_id,"stop_capture")
    active = service.action(view.session_id,"activate")
    assert calls == [] and active.listening and len(active.waveform) == 8
    assert all(0 <= value <= 1 for value in active.waveform)
    with pytest.raises(SessionError): service.action(view.session_id,"activate")
    done = service.action(view.session_id,"stop_capture")
    assert done.state == State.COMPLETED and calls == [True] and done.waveform == ()
    assert not service.hub._active
    with pytest.raises(SessionError): service.action(view.session_id,"activate")


@pytest.mark.parametrize("action",["cancel","stop_capture"])
def test_capture_end_clears_waveform(service,action):
    key = service.create("read_volume").session_id
    service.action(key,"activate")
    assert service.action(key,action).waveform == ()


def test_wrong_speaker_before_command_stt(service,monkeypatch):
    counts=[]
    original=DemoDriver.close
    def close(self): counts.append((self.h.capture_count,self.h.stt_calls,self.backend_calls)); original(self)
    monkeypatch.setattr(DemoDriver,"close",close)
    result=pending(service,"wrong_speaker")
    assert result.state == State.BLOCKED and result.authentication == "rejected"
    assert counts == [(2,1,0)]


def test_clarification_only_existing_approved_candidate_and_replan(service):
    view=pending(service,"ambiguous_application")
    assert view.state == State.CLARIFICATION
    assert [(c.candidate_id,c.display_name) for c in view.clarification.candidates] == [("chrome","Chrome")]
    request=view.clarification.request_id
    view=service.action(view.session_id,"clarify",request_id=request,candidate_id="chrome")
    assert view.state == State.CONFIRMATION and view.canonical_command == "Open chrome"
    assert view.policy == "confirmation_required" and view.risk == "low"
    with pytest.raises(SessionError): service.action(view.session_id,"clarify",request_id=request,candidate_id="chrome")
    result=service.action(view.session_id,"confirm",request_id=view.confirmation.request_id,decision="confirm")
    assert result.verified and result.execution_permitted is False and result.confirmation_mode == "synthetic_ui_demo"


@pytest.mark.parametrize("fault",["candidate","request","command","session"])
def test_clarification_binding(service,fault):
    view=pending(service,"ambiguous_application")
    session=service.sessions[view.session_id]
    key=view.clarification.request_id
    candidate="chrome"
    if fault=="candidate": candidate="notepad"
    if fault=="request": key=uuid4()
    if fault=="command": session.driver.text="open notepad"
    if fault=="session": session.pending["session"]=uuid4()
    with pytest.raises(SessionError): service.action(view.session_id,"clarify",request_id=key,candidate_id=candidate)
    assert session.state == State.BLOCKED and session.pending is None


@pytest.mark.parametrize("scenario",["ambiguous_application","calculator_confirm"])
def test_expiry_no_backend_and_no_reuse(service,scenario,monkeypatch):
    calls=[]
    original=DemoDriver.close
    def close(self): calls.append(self.backend_calls); original(self)
    monkeypatch.setattr(DemoDriver,"close",close)
    view=pending(service,scenario)
    service.test_clock[0]=31
    result=service.action(view.session_id,"view")
    assert result.state == State.TIMED_OUT and calls == [0]
    assert result.clarification is result.confirmation is None


@pytest.mark.parametrize("fault",["plan","request","session"])
def test_confirmation_binding(service,fault):
    view=pending(service)
    session=service.sessions[view.session_id]
    request=view.confirmation.request_id
    if fault=="request": request=uuid4()
    if fault=="plan": session.plan=session.plan.model_copy(update={"application_id":"chrome"})
    if fault=="session": session.pending["session"]=uuid4()
    with pytest.raises(SessionError): service.action(view.session_id,"confirm",request_id=request,decision="confirm")
    assert session.state == State.BLOCKED


def test_history_event_privacy_and_bounds(service):
    service=SessionService(Configuration(max_sessions=1,max_history=2,max_events=24),
                           clock=service.clock,hub=service.hub)
    for _ in range(4):
        view=pending(service,"read_volume")
        assert view.verified
    assert len(service.history)==2 and len(service.sessions)==1
    public=json.dumps([entry.model_dump(mode="json") for entry in service.history])
    assert not any(key in public for key in ("transcript","profile","phrase","embedding","score","path"))
    session=service.sessions[view.session_id]
    assert len(session.events)<=24
    assert [e.sequence for e in session.events] == sorted(e.sequence for e in session.events)


def test_capacity_and_expiry(service):
    service.config=Configuration(max_sessions=1)
    key=service.create("read_volume").session_id
    with pytest.raises(SessionError,match="capacity"): service.create("read_volume")
    service.test_clock[0]=121
    assert service.action(key,"view").state == State.TIMED_OUT
    assert service.create("read_volume").session_id != key


def test_transcript_policy_and_terminal_cleanup(service):
    view=pending(service,show=True)
    assert view.transcript is None
    service.action(view.session_id,"cancel")
    service.config=Configuration(transcript_display=True)
    view=pending(service,show=True)
    assert view.transcript == "open calculator"
    result=service.action(view.session_id,"cancel")
    assert result.transcript is None and service.sessions[view.session_id].driver is None


def test_emergency_stop_reset_unavailable_and_production_locked(service):
    key=service.create("read_volume").session_id
    service.emergency_stop()
    assert service.action(key,"view").state == State.STOPPED
    with pytest.raises(SessionError,match="emergency_stop"): service.create("read_volume")
    with pytest.raises(SessionError,match="reset_unavailable"): service.reset_emergency_stop()
    with pytest.raises(SessionError,match="calibration_blocked"): service.production()
    assert service.hub.stopped.is_set()


def test_cancel_during_command_speaker_inference_blocks_stt(service,monkeypatch):
    original=DemoDriver.authenticate
    counts=[]
    close=DemoDriver.close
    def authenticated(self):
        original(self)
        extract=self.h.engine.extract
        def stopped(audio,**kwargs):
            vector=extract(audio,**kwargs)
            self.h.pilot.cancel.set()
            return vector
        self.h.engine.extract=stopped
    def closed(self): counts.append(self.h.stt_calls); close(self)
    monkeypatch.setattr(DemoDriver,"authenticate",authenticated)
    monkeypatch.setattr(DemoDriver,"close",closed)
    view=pending(service,"read_volume")
    assert view.state == State.CANCELLED and counts==[1]
    assert not service.hub._active


def test_fake_notepad_launch_registry_and_unknown_target():
    from app.execution.models import FakePlan, FakeStep
    from app.execution.registry import validate_plan
    from app.planning.models import Arguments, Capability
    for name in ("notepad","calculator"):
        plan=FakePlan(steps=(FakeStep(step_id="step-1",capability=Capability.LAUNCH,arguments=Arguments(application=name)),))
        assert validate_plan(plan)==plan
    with pytest.raises(Exception):
        validate_plan(FakePlan(steps=(FakeStep(step_id="step-1",capability=Capability.LAUNCH,
            arguments=Arguments(application="whatsapp")),)))
