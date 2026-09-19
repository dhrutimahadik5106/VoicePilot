"""Explicit manual operator evidence, separate from fake and voice authority."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from threading import Lock
from uuid import uuid4
from app.launch.models import Configuration, LaunchPlan, Permit, LaunchError, Status


def plan_document(plan):
    if type(plan) is not LaunchPlan:
        raise LaunchError(Status.INVALID_AUTHORIZATION)
    document = plan.model_dump(mode="json") | {"identity": plan.identity, "authentication_id": str(plan.authentication_id) if plan.authentication_id else None}
    LaunchPlan.model_validate(document)
    return document


def digest(plan):
    return sha256(json.dumps(plan_document(plan), sort_keys=True).encode()).hexdigest()


class ManualAuthority:
    mode = "manual_operator_test"

    def __init__(self, configuration=None, *, clock=lambda: datetime.now(timezone.utc)):
        config = configuration or Configuration()
        self.configuration = Configuration.model_validate(config.model_dump())
        self.clock = clock
        self._pending = {}
        self._issued = {}
        self._used_plans = set()
        self._lock = Lock()

    def allowed(self, plan):
        return (plan.mode == self.mode and self.configuration.manual_launch_testing_enabled
                and plan.authentication_id is None)

    def challenge(self, plan, *, typed_application):
        with self._lock:
            if (not self.allowed(plan)
                    or not self.configuration.windows_adapter_enabled
                    or typed_application != plan.application_id
                    or plan.application_id not in self.configuration.approved_application_ids
                    or len(self._pending) + len(self._issued) >= 100):
                raise LaunchError(Status.INVALID_AUTHORIZATION)
            key = uuid4()
            self._pending[key] = (digest(plan), self.clock() + timedelta(seconds=self.configuration.authorization_expiry))
            return key

    def confirm(self, key, plan, *, response):
        with self._lock:
            record = self._pending.pop(key, None)
            if (record is None or response != "LAUNCH " + plan.application_id
                    or record[0] != digest(plan) or self.clock() >= record[1]):
                raise LaunchError(Status.INVALID_AUTHORIZATION)
            permit = Permit()
            self._issued[permit.handle] = (record[0], record[1])
            return permit

    def consume(self, plan, permit):
        with self._lock:
            try:
                if type(permit) is not Permit:
                    return False
                record = self._issued.pop(permit.handle, None)
                if (record is None or record[0] != digest(plan) or self.clock() >= record[1]
                        or plan.plan_id in self._used_plans or len(self._used_plans) >= 100):
                    return False
                if not self.allowed(plan):
                    return False
                self._used_plans.add(plan.plan_id)
                return record[1]
            except Exception:
                return False


class VoiceAuthority(ManualAuthority):
    """Only prepares authority through the existing authenticated audio service."""
    mode = "authenticated_voice"

    def __init__(self, settings, backend, *, pipeline=None, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(settings.launch, clock=clock)
        self.settings = settings
        self.backend = backend
        self.pipeline = pipeline
        self._authenticated = {}

    def allowed(self, plan):
        return (plan.mode == self.mode and self.configuration.real_execution_enabled
                and plan.authentication_id is not None
                and self._authenticated.get(plan.plan_id, (None, self.clock()))[0] == digest(plan)
                and self.clock() < self._authenticated[plan.plan_id][1])

    def prepare(self, audio, profile_id, *, policy_id=None, cancel=None):
        if (not self.configuration.real_execution_enabled or not self.settings.speaker_verification_enabled
                or self.settings.speaker.calibration_state != "validated" or len(self._authenticated) >= 100):
            raise LaunchError(Status.ACCESS_DENIED)
        if self.pipeline is None:
            from app.pipeline.service import DiagnosticService, SpeakerInspection
            self.pipeline = DiagnosticService(self.settings, verifier=SpeakerInspection(self.settings, policy_id))
        from app.pipeline.models import Trace
        try:
            trace = self.pipeline.audio(audio, authenticated=True, profile_id=profile_id, cancel=cancel)
            if type(trace) is not Trace:
                raise ValueError()
            trace = Trace.model_validate(trace.model_dump())
        except Exception:
            raise LaunchError(Status.ACCESS_DENIED) from None
        if (trace.authentication != "policy_verified" or trace.status != "completed"
                or trace.resolver_status != "resolved" or trace.intent != "open_application"
                or trace.plan is None or trace.plan.status != "ready"
                or trace.plan.overall_risk != "low" or trace.plan.requires_confirmation
                or tuple(s.action for s in trace.plan.steps) != ("launch", "verify")):
            raise LaunchError(Status.ACCESS_DENIED)
        application_id = trace.plan.steps[0].arguments.application
        if application_id not in self.configuration.approved_application_ids:
            raise LaunchError(Status.UNSUPPORTED)
        discovery = self.backend.discover(application_id, self.configuration.discovery_timeout)
        if discovery.status != Status.AVAILABLE or not discovery.identity:
            raise LaunchError(discovery.status)
        plan = LaunchPlan(application_id=application_id, identity=discovery.identity,
                          mode=self.mode, authentication_id=trace.trace_id)
        self._authenticated[plan.plan_id] = (digest(plan), self.clock() + timedelta(seconds=self.configuration.authorization_expiry))
        return plan
