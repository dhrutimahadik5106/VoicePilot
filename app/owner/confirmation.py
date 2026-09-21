"""Private, process-local confirmation binding; hashes are integrity identifiers only."""
from hashlib import sha256
from dataclasses import dataclass, field
from uuid import uuid4

from app.owner.models import OwnerError
from app.operations.models import Capability as C, Plan
from app.operations.authorization import binding as operation_binding
from app.launch.models import LaunchPlan
from app.launch.authorization import digest as launch_binding

POLICY = "owner-confirmation-v1"
READ_ONLY = frozenset({C.VOLUME_READ, C.MUTE_READ, C.BRIGHTNESS_READ})
SAFETY = frozenset({C.STOP, C.CANCEL})
MUTATIONS = frozenset({C.VOLUME_UP, C.VOLUME_DOWN, C.VOLUME_SET, C.MUTE, C.UNMUTE})
LIFETIME = 30


def normalized_command(text):
    if type(text) is not str or not 0 < len(text) <= 120:
        raise OwnerError("unsupported_command")
    return text.strip().casefold().rstrip(".?!").strip()


def plan_binding(plan):
    if type(plan) is LaunchPlan:
        return launch_binding(plan)
    if type(plan) is Plan:
        return operation_binding(plan)
    raise OwnerError("binding_mismatch")


def requires_confirmation(plan):
    plan_binding(plan)
    if type(plan) is LaunchPlan:
        if plan.application_id not in {"notepad", "calculator", "chrome"}:
            raise OwnerError("unsupported_command")
        return True
    if plan.capability in READ_ONLY | SAFETY:
        return False
    if plan.capability not in MUTATIONS:
        raise OwnerError("unsupported_command")
    return True


def prompt(plan):
    # Only closed typed values are displayed, never a transcript or identity hash.
    if type(plan) is LaunchPlan:
        return "Open " + plan.application_id + ". Say only Confirm or Cancel."
    suffix = " " + str(plan.percentage) + " percent" if plan.percentage is not None else ""
    return plan.capability.value + suffix + ". Say only Confirm or Cancel."


@dataclass(frozen=True, repr=False)
class ConfirmationCapture:
    """Capture purpose marker only; never authorization evidence."""
    message: str = field(repr=False)

    def __repr__(self):
        return "ConfirmationCapture()"


class PendingConfirmation:
    """One private outstanding request. It cannot be serialized into a reusable grant."""
    def __init__(self, plan, text, context, expires):
        self._nonce = uuid4()
        self._plan = plan_binding(plan)
        self._command = sha256(normalized_command(text).encode()).digest()
        self._context = context
        self._policy = POLICY
        self._expires = expires
        self._used = False

    def __repr__(self):
        return "PendingConfirmation()"

    def __reduce__(self):
        raise OwnerError("access_denied")

    def check(self, plan, text, context, now):
        if self._used:
            raise OwnerError("confirmation_replayed")
        if now >= self._expires:
            raise OwnerError("confirmation_expired")
        if (plan_binding(plan) != self._plan or self._context != context
                or self._command != sha256(normalized_command(text).encode()).digest()
                or self._policy != POLICY):
            raise OwnerError("binding_mismatch")

    def consume(self, plan, text, context, now):
        try:
            self.check(plan, text, context, now)
        finally:
            self._used = True


def policy_document():
    return {"version": POLICY, "confirmation_seconds": LIFETIME,
            "read_only": sorted(c.value for c in READ_ONLY),
            "state_changing": sorted(c.value for c in MUTATIONS) + ["application.launch"],
            "safety_controls": sorted(c.value for c in SAFETY),
            "responses": ["confirm", "cancel"], "fresh_speaker_verification": True,
            "extends_authentication": False}
