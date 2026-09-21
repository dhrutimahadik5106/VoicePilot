"""Explicit synthetic adapter: real-controller run methods are never called."""
from uuid import uuid4
from app.owner.fakes import Harness
from app.owner.models import OwnerError
from app.owner.pilot import resolve
from app.launch.models import LaunchPlan
from app.execution.models import FakePlan, FakeStep, State
from app.execution.authorization import FakeAuthority
from app.execution.controller import Controller
from app.execution.adapters import Scenario
from app.execution.evaluation import authorize_fixture
from app.planning.models import Arguments, Capability

TEXT = {
    "read_volume":"what is the volume", "calculator_confirm":"open calculator",
    "chrome_cancel":"open chrome", "ambiguous_application":"open browser",
    "unknown_application":"open unknown", "wrong_speaker":"what is the volume",
    "confirmation_expiry":"open calculator", "emergency_stop":"open calculator",
    "verification_failure":"open calculator", "history_entry":"what is the volume",
}


class DemoDriver:
    def __init__(self, scenario, cancel=None):
        self.h = Harness().calibrate()
        if cancel is not None:
            self.h.pilot.cancel = cancel
            self.h.calibration.cancel = cancel
        self.scenario = scenario
        self.h.command = TEXT[scenario]
        if scenario == "wrong_speaker": self.h.command_score = .2
        self.session = uuid4()
        self.auth = self.row = self.guard = self.plan = None
        self.text = ""
        self.backend_calls = 0

    def authenticate(self):
        result = self.h.pilot.authenticate(self.h.profile.profile_id, self.session)
        if result.status != "accepted": raise OwnerError(result.reason)
        self.auth = result.evidence
        self.row = self.h.pilot._evidence.pop(self.auth.nonce)
        self.guard = lambda: self.h.pilot.check(self.auth, self.session, consumed=self.row)

    def understand(self):
        # The existing Phase 6C speaker-before-STT and same-capture boundary.
        result, audio_id, digest = self.h.pilot._speech(self.session, self.row, self.guard, "command")
        self.row.update(command_id=audio_id, command_digest=digest)
        self.text = result.normalized_transcript
        return self.text

    def prepare(self, text):
        selected = resolve(text)
        self.plan = LaunchPlan(application_id=selected, identity="a" * 64,
            mode="authenticated_voice", authentication_id=self.auth.nonce) if type(selected) is str else selected
        return self.plan

    def confirm(self):
        self.guard = self.h.pilot._confirm(self.plan, self.text, self.session, self.row, self.guard)

    def execute(self, cancel):
        self.guard()
        if cancel.is_set(): raise OwnerError("cancelled")
        self.backend_calls += 1
        if type(self.plan) is LaunchPlan:
            # Separate Phase 5B synthetic authority: owner/demo evidence is NEVER
            # submitted to production launch or operations controllers.
            plan = FakePlan(steps=(FakeStep(step_id="step-1", capability=Capability.LAUNCH,
                arguments=Arguments(application=self.plan.application_id)),))
            authority = FakeAuthority()
            request = authorize_fixture(authority, plan)
            scenario = Scenario.FALSE_SUCCESS if self.scenario == "verification_failure" else Scenario.SUCCESS
            result = Controller().run_fake(plan, request, authority, scenario=scenario, cancel=cancel)
            return result.state == State.SUCCEEDED and result.evidence == "verified_success"
        before = self.h.backend.read_volume()
        after = self.h.backend.read_volume()
        return before == after and not cancel.is_set()

    def close(self):
        self.h.pilot.cancel.set()
        self.h.pilot._evidence.clear()
        self.h.pilot._confirmation = None
        self.h.audio_text.clear()
        self.h.audio_scores.clear()
        self.h.last_audio = None
        self.auth = self.row = self.guard = self.plan = None
        self.text = ""
