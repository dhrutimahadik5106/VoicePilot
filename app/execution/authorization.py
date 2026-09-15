"""In-memory synthetic evidence issuer; deliberately no production authorization API."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from threading import RLock
from uuid import uuid4

from app.execution.models import (Authentication, Authorization, Binding, Confirmation,
                                  Configuration, ExecutionError, Request)
from app.execution.registry import plan_document, step_document, validate_plan


def digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def binding_for(plan, step_id):
    plan = validate_plan(plan)
    step = next((s for s in plan.steps if s.step_id == step_id), None)
    if step is None:
        raise ExecutionError()
    return plan, step, digest(plan_document(plan)), digest(step_document(step))


class FakeAuthority:
    """Trusted synthetic harness only. Handles have no meaning outside this instance."""
    def __init__(self, configuration=None, *, clock=lambda: datetime.now(timezone.utc)):
        self.configuration = configuration or Configuration()
        self.clock = clock
        self._auth = {}
        self._challenges = {}
        self._confirmations = {}
        self._tokens = {}
        self._admitted = set()
        self._lock = RLock()

    def _now(self):
        now = self.clock()
        if now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
            raise ExecutionError()
        return now

    def _expiry(self):
        count = sum(map(len, (self._auth, self._challenges, self._confirmations, self._tokens)))
        if count >= self.configuration.max_entries:
            raise ExecutionError()
        return self._now() + timedelta(seconds=self.configuration.evidence_ttl)

    def synthetic_authentication(self, plan, *, status="verified", calibration="validated"):
        with self._lock:
            if status != "verified" or calibration != "validated":
                raise ExecutionError()
            plan = validate_plan(plan)
            receipt = Authentication()
            self._auth[receipt.handle] = (digest(plan_document(plan)), self._expiry())
            return receipt

    def challenge(self, plan, step_id):
        with self._lock:
            _, step, pd, sd = binding_for(plan, step_id)
            key = uuid4()
            self._challenges[key] = (pd, sd, self._expiry())
            # Deliberate review surface only, never added to audit events.
            return key, {"effect": "change synthetic in-memory state only",
                         "plan_id": str(plan.plan_id), "version": plan.version,
                         "step": step_document(step)}

    def confirm(self, key, plan, step_id, *, decision):
        with self._lock:
            challenge = self._challenges.pop(key, None)
            _, _, pd, sd = binding_for(plan, step_id)
            if (challenge is None or decision != "approve_fake_effect"
                    or challenge[:2] != (pd, sd) or self._now() >= challenge[2]):
                raise ExecutionError()
            receipt = Confirmation()
            self._confirmations[receipt.handle] = (pd, sd, challenge[2])
            return receipt

    def issue(self, plan, step_id, authentication, confirmation):
        with self._lock:
            plan, step, pd, sd = binding_for(plan, step_id)
            if type(authentication) is not Authentication or type(confirmation) is not Confirmation:
                raise ExecutionError()
            auth = self._auth.pop(authentication.handle, None)
            consent = self._confirmations.pop(confirmation.handle, None)
            now = self._now()
            if (auth is None or consent is None or auth[0] != pd or consent[:2] != (pd, sd)
                    or now >= min(auth[1], consent[2])):
                raise ExecutionError()
            token = Authorization()
            binding = Binding(plan_id=plan.plan_id, plan_digest=pd, step_id=step_id,
                              step_digest=sd, capability=step.capability, arguments=step.arguments,
                              authentication_id=authentication.handle,
                              confirmation_id=confirmation.handle,
                              expires_at=min(auth[1], consent[2], self._expiry()))
            request = Request(binding=binding, authorization=token)
            self._tokens[token.handle] = request
            return request

    def consume(self, plan, request):
        """Consume atomically before adapter entry, including on a mismatched attempt."""
        with self._lock:
            try:
                if type(request) is not Request or type(request.authorization) is not Authorization:
                    return False
                recorded = self._tokens.pop(request.authorization.handle, None)
                if recorded is None or recorded != request:
                    return False
                b = request.binding
                _, step, pd, sd = binding_for(plan, b.step_id)
                valid = (b.plan_id == plan.plan_id and b.plan_digest == pd and b.step_digest == sd
                         and b.capability == step.capability and b.arguments == step.arguments
                         and b.policy_version == self.configuration.policy_version
                         and self._now() < b.expires_at)
                key = (b.plan_id, b.step_id)
                if not valid or key in self._admitted or len(self._admitted) >= self.configuration.max_entries:
                    return False
                self._admitted.add(key)
                return True
            except Exception:
                return False
