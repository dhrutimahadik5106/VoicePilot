"""Closed adapter contract implementations; observations remain controller-owned."""
from app.operations.models import Plan, Capability as C, Code, OperationError, validate_plan, Volume, Brightness
from app.operations.registry import REGISTRY


class StateAdapter:
    input_schema = Plan

    def __init__(self, capability, backend, before, target, guard):
        if capability not in set(C) or not capability.value.startswith(("system.volume.", "system.brightness.")):
            raise OperationError(Code.UNSUPPORTED)
        self.capability, self.backend = capability, backend
        self.before, self.target, self.guard = before, target, guard
        self.spec = REGISTRY[capability]

    def precondition(self, step):
        return validate_plan(step).capability == self.capability

    def execute(self, key, step, cancel):
        if not self.precondition(step) or cancel.is_set():
            raise OperationError(Code.CANCELLED)
        self.guard()
        if self.capability in {C.MUTE, C.UNMUTE}:
            self.backend.set_mute(self.target, self.before.endpoint, self.guard)
        elif self.capability in {C.VOLUME_SET, C.VOLUME_UP, C.VOLUME_DOWN}:
            self.backend.set_volume(self.target, self.before.endpoint, self.guard)
        elif self.capability in {C.BRIGHTNESS_SET, C.BRIGHTNESS_UP, C.BRIGHTNESS_DOWN}:
            self.backend.set_brightness(self.target, self.before.target, self.guard)
        else:
            raise OperationError(Code.UNSUPPORTED)
        return True

    def observe(self, key):
        return self.backend.read_volume() if self.capability.value.startswith("system.volume.") else self.backend.read_brightness()

    def verify(self, step, before, after):
        # Advisory only. The controller applies its own independent-state comparison.
        if not self.precondition(step):
            return False
        if type(before) is Volume and type(after) is Volume:
            percent = before.percent if self.capability in {C.MUTE, C.UNMUTE} else self.target
            muted = self.target if self.capability in {C.MUTE, C.UNMUTE} else before.muted
            return (after.endpoint == before.endpoint and after.percent == percent
                    and after.muted is muted)
        if type(before) is Brightness and type(after) is Brightness:
            return after.supported and after.target == before.target and after.percent == self.target
        return False

    def rollback(self, key, before, cancel):
        return False


class ScreenshotAdapter:
    input_schema = Plan

    def __init__(self, capability, backend, store, guard):
        if capability not in {C.SCREENSHOT, C.SCREENSHOT_DELETE}:
            raise OperationError(Code.UNSUPPORTED)
        self.capability, self.backend, self.store, self.guard = capability, backend, store, guard
        self.spec = REGISTRY[capability]
        self.artifact_id = None

    def precondition(self, step):
        return validate_plan(step).capability == self.capability

    def execute(self, key, step, cancel):
        if not self.precondition(step) or cancel.is_set():
            raise OperationError(Code.CANCELLED)
        self.guard()
        if self.capability == C.SCREENSHOT:
            data = self.backend.capture(self.guard)
            self.guard()
            self.artifact_id = self.store.save(data, guard=self.guard)
        else:
            self.artifact_id = step.artifact_id
            self.store.delete(self.artifact_id, guard=self.guard)
        return True

    def observe(self, key):
        return self.store.verify(self.artifact_id) if self.capability == C.SCREENSHOT else self.store.exists(self.artifact_id)

    def verify(self, step, before, after):
        if not self.precondition(step):
            return False
        if self.capability == C.SCREENSHOT:
            return (type(after) is tuple and len(after) == 2
                    and all(type(value) is int and 0 < value <= 16384 for value in after))
        return after is False

    def rollback(self, key, before, cancel):
        return False
