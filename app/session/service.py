"""One bounded application service; production capture/admission remains locked."""
from collections import OrderedDict, deque
from datetime import datetime, timezone
from hashlib import sha256
from threading import Event, RLock
from time import monotonic
from uuid import uuid4

from app.commands.resolver import CommandResolver
from app.execution.cancellation import GLOBAL
from app.launch.models import LaunchPlan
from app.owner.confirmation import plan_binding, requires_confirmation
from app.owner.models import OwnerError
from app.operations.registry import REGISTRY
from app.session.demo import DemoDriver, TEXT
from app.session.models import (Configuration, State, View, Card, Candidate, TTS, PublicEvent,
                                HistoryEntry, SessionError)
from app.session.state import TERMINAL, transition


class VoicePilotSession:
    def __init__(self, scenario, config, clock, hub, finish, resolver, show_transcript=False):
        if scenario not in TEXT: raise SessionError()
        self.id, self.scenario = uuid4(), scenario
        self.config, self.clock, self.hub, self.finish, self.resolver = config, clock, hub, finish, resolver
        self.started, self.deadline = clock(), clock() + config.session_timeout
        self.state = State.IDLE
        self.events = deque(maxlen=config.max_events)
        self.sequence = 0
        self.cancel_signal = Event()
        self.driver = None
        self.pending = None
        self.plan = None
        self.transcript = None
        self.show_transcript = show_transcript and config.transcript_display
        self.waveform = ()
        self.last_waveform = float("-inf")
        self.risk, self.policy, self.explanation = "unsupported", "disabled", "not_planned"
        self.capability, self.canonical = "none", None
        self.confirmation_required = self.confirmation_received = self.verified = False
        self.reason = "ok"
        self.authentication = "synthetic_demo"
        self.move(State.READY)
        self.move(State.ACTIVATION)

    def move(self, state, reason="ok"):
        self.state = transition(self.state, state)
        self.reason = reason
        self.sequence += 1
        self.events.append(PublicEvent(sequence=self.sequence, session_id=self.id, state=state, reason=reason))
        if state != State.LISTENING: self.waveform = ()
        if state in TERMINAL:
            self.pending = self.plan = None
            self.transcript = None
            if self.driver is not None:
                self.driver.close()
                self.driver = None
            self.finish(self)

    def check(self):
        if self.state in TERMINAL: return
        if self.hub.stopped.is_set(): self.move(State.STOPPED, "emergency_stop")
        elif self.cancel_signal.is_set(): self.move(State.CANCELLED, "cancelled")
        elif self.clock() >= self.deadline or (self.pending and self.clock() >= self.pending["expires"]):
            self.move(State.TIMED_OUT, "expired")
        if self.driver is not None:
            self.driver.h.now = self.clock() - self.started

    def require(self, state):
        self.check()
        if self.state != state: raise SessionError("invalid_transition")

    def activate(self):
        self.require(State.ACTIVATION)
        self.move(State.LISTENING)
        self.update_waveform()

    def update_waveform(self):
        if self.state == State.LISTENING and self.config.waveform_enabled and self.clock() - self.last_waveform >= .25:
            self.last_waveform = self.clock()
            self.waveform = (0., .125, .375, .625, .5, .25, .125, 0.)

    def stop_capture(self):
        self.require(State.LISTENING)
        with self.hub.track(self.cancel_signal):
            try:
                self.move(State.AUTHENTICATING)
                self.driver = DemoDriver(self.scenario,self.cancel_signal)
                self.driver.h.now = self.clock() - self.started
                self.driver.authenticate()
                self.check()
                if self.state in TERMINAL: return
                # Wrong command speakers are rejected by existing Phase 6C before STT.
                text = self.driver.understand()
                self.move(State.UNDERSTANDING)
                if self.show_transcript: self.transcript = TEXT[self.scenario]
                if self.scenario == "ambiguous_application":
                    result = self.resolver.resolve(text)
                    names = {"notepad":"Notepad", "calculator":"Calculator", "chrome":"Chrome"}
                    candidates = tuple(Candidate(candidate_id=c.entity_id, display_name=names[c.entity_id])
                        for c in result.candidates if c.entity_id in names)[:3]
                    if not candidates: raise SessionError("unsupported")
                    self.pending = {"id":uuid4(), "session":self.id, "digest":sha256(text.encode()).digest(),
                        "text":text, "candidates":candidates,
                        "expires":min(self.deadline,self.clock()+self.config.clarification_expiry)}
                    self.move(State.CLARIFICATION)
                    return
                self.prepare(text)
            except (OwnerError, SessionError) as error:
                self.fail(error.code)
            except Exception:
                self.fail("invalid_request")

    def fail(self, reason):
        if self.state not in TERMINAL:
            if reason == "cancelled":
                self.move(State.CANCELLED,"cancelled")
                return
            if reason == "speaker_rejected": self.authentication = "rejected"
            self.policy = "unsupported" if reason in {"unsupported", "unsupported_command"} else "blocked"
            self.move(State.BLOCKED, "unsupported" if reason == "unsupported_command" else SessionError(reason).code)

    def prepare(self, text):
        self.move(State.PLANNING)
        self.plan = self.driver.prepare(text)
        self.move(State.RISK)
        self.confirmation_required = requires_confirmation(self.plan)
        launch = type(self.plan) is LaunchPlan
        self.capability = "application.launch" if launch else self.plan.capability.value
        self.canonical = "Open " + self.plan.application_id if launch else self.capability
        self.risk = "low" if launch else REGISTRY[self.plan.capability].risk
        self.explanation = "reversible_action" if self.confirmation_required else "informational_read"
        self.policy = "confirmation_required" if self.confirmation_required else "allowed"
        if self.confirmation_required:
            self.pending = {"id":uuid4(), "session":self.id, "digest":plan_binding(self.plan),
                "expires":min(self.deadline,self.clock()+30), "candidates":()}
            self.move(State.CONFIRMATION)
        else:
            self.execute()

    def clarify(self, request_id, candidate_id):
        self.require(State.CLARIFICATION)
        pending, self.pending = self.pending, None
        if (pending["id"] != request_id or pending["session"] != self.id
                or sha256(self.driver.text.encode()).digest() != pending["digest"]
                or candidate_id not in {c.candidate_id for c in pending["candidates"]}):
            self.fail("binding_mismatch")
            raise SessionError("binding_mismatch")
        try:
            self.prepare("open " + candidate_id)
        except Exception:
            self.fail("unsupported")

    def confirm(self, request_id, decision):
        self.require(State.CONFIRMATION)
        pending, self.pending = self.pending, None
        if (pending["id"] != request_id or pending["session"] != self.id
                or pending["digest"] != plan_binding(self.plan) or decision not in {"confirm", "cancel"}):
            self.fail("binding_mismatch")
            raise SessionError("binding_mismatch")
        if decision == "cancel":
            self.cancel()
            return
        try:
            self.driver.confirm()  # Separate generated capture; never real UI biometric evidence.
            self.confirmation_received = True
            self.execute()
        except OwnerError as error:
            self.fail(error.code)
        except Exception:
            self.fail("invalid_request")

    def execute(self):
        self.check()
        if self.state in TERMINAL: return
        with self.hub.track(self.cancel_signal):
            self.move(State.AUTHORIZED)
            self.move(State.EXECUTING)
            verified = self.driver.execute(self.cancel_signal)
            self.check()
            if self.state in TERMINAL: return
            self.move(State.OBSERVING)
            self.move(State.VERIFYING)
            if not verified:
                self.move(State.FAILED,"verification_failed")
                return
            self.verified = True
            self.move(State.RESPONDING)
            self.move(State.COMPLETED)

    def cancel(self):
        self.check()
        if self.state in TERMINAL: raise SessionError("replayed")
        self.cancel_signal.set()
        self.move(State.CANCELLED,"cancelled")

    def view(self):
        self.check()
        self.update_waveform()
        clarification = confirmation = None
        if self.pending:
            card = Card(request_id=self.pending["id"], candidates=self.pending["candidates"],
                expires_in_seconds=max(0,self.pending["expires"]-self.clock()),
                prompt_code="choose_application" if self.state == State.CLARIFICATION else "confirm_synthetic_action",
                reason="ambiguous_application" if self.state == State.CLARIFICATION else "state_change")
            if self.state == State.CLARIFICATION: clarification = card
            else: confirmation = card
        conversation = "needs_clarification" if clarification else "needs_confirmation" if confirmation else (
            "resolved" if self.verified else "cancelled" if self.state == State.CANCELLED else
            "unsupported" if self.policy == "unsupported" else "blocked")
        response = "completed" if self.verified else "cancelled" if self.state == State.CANCELLED else (
            "expired" if self.state == State.TIMED_OUT else "verification_failed" if self.state == State.FAILED else
            "blocked" if self.state in TERMINAL else "ready")
        return View(session_id=self.id,state=self.state,state_label=self.state.value,
            listening=self.state == State.LISTENING,authentication=self.authentication,
            transcript_visibility="transient_synthetic" if self.transcript else "hidden", transcript=self.transcript,
            canonical_command=self.canonical, corrected_interpretation=self.canonical,
            risk=self.risk,policy=self.policy,risk_explanation=self.explanation,
            plan_summary=(self.capability,"observe","verify") if self.canonical else (),
            conversation=conversation,clarification=clarification,confirmation=confirmation,waveform=self.waveform,
            progress=100 if self.state in TERMINAL else 0,verified=self.verified,reason=self.reason,
            duration_seconds=min(3600,max(0,self.clock()-self.started)),tts=TTS(response_code=response),
            final_response={"ready":"Ready","completed":"Completed in simulation","blocked":"Blocked",
                            "cancelled":"Cancelled","expired":"Expired","verification_failed":"Verification failed"}[response],
            emergency_stopped=self.hub.stopped.is_set())


class SessionService:
    def __init__(self, configuration=None, *, clock=monotonic, hub=None, resolver=None):
        self.config = configuration or Configuration()
        self.clock, self.hub = clock, hub or GLOBAL
        self.resolver = resolver
        self.sessions = OrderedDict()
        self.history = deque(maxlen=self.config.max_history)
        self.lock = RLock()
        self.closed = False

    def finish(self, session):
        self.history.append(HistoryEntry(session_id=session.id,timestamp=datetime.now(timezone.utc).isoformat(),
            capability=session.capability,state=session.state,risk=session.risk,
            confirmation_required=session.confirmation_required,confirmation_received=session.confirmation_received,
            verified=session.verified,duration_seconds=min(3600,max(0,self.clock()-session.started)),reason=session.reason))

    def create(self, scenario, show_transcript=False):
        with self.lock:
            if self.closed or not self.config.demo_enabled: raise SessionError("disabled")
            if self.hub.stopped.is_set(): raise SessionError("emergency_stop")
            for session in tuple(self.sessions.values()): session.check()
            if len(self.sessions) >= self.config.max_sessions:
                expired = next((key for key,s in self.sessions.items() if s.state in TERMINAL),None)
                if expired is None: raise SessionError("capacity")
                del self.sessions[expired]
            if self.resolver is None: self.resolver = CommandResolver.from_directory()
            session = VoicePilotSession(scenario,self.config,self.clock,self.hub,self.finish,self.resolver,show_transcript)
            self.sessions[session.id] = session
            return session.view()

    def action(self, session_id, action, **kwargs):
        with self.lock:
            if self.closed: raise SessionError("disabled")
            session = self.sessions.get(session_id)
            if session is None: raise SessionError("not_found")
            operations = {"activate":session.activate,"stop_capture":session.stop_capture,"clarify":session.clarify,
                          "confirm":session.confirm,"cancel":session.cancel,"view":lambda:None}
            if action not in operations: raise SessionError()
            operations[action](**kwargs)
            return session.view()

    def emergency_stop(self):
        self.hub.cancel(emergency=True)
        with self.lock:
            for session in self.sessions.values(): session.check()

    def reset_emergency_stop(self):
        raise SessionError("reset_unavailable")  # Existing hub has no safe reset policy.

    def production(self):
        raise SessionError("calibration_blocked")  # No real profile access or UI evidence conversion.

    def close(self):
        with self.lock:
            for session in self.sessions.values():
                if session.state not in TERMINAL: session.cancel()
            self.sessions.clear()
            self.history.clear()
            self.closed = True
