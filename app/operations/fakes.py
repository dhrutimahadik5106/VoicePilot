"""Synthetic, in-memory backend for tests/evaluation only; no native imports."""
from app.operations.models import Volume, Brightness, OperationError, Code


class FakeBackend:
    fake = True

    def __init__(self):
        self.volume = Volume(percent=40, muted=False, endpoint="synthetic-default")
        self.brightness = Brightness(supported=True, percent=50, mutation_supported=True)
        self.mutations = 0
        self.reads = 0
        self.false_success = False
        self.fail_read = False
        self.fail_write = False
        self.after_write = lambda: None

    def read_volume(self):
        self.reads += 1
        if self.fail_read:
            raise OperationError(Code.NO_OBSERVATION)
        return self.volume

    def set_volume(self, value, endpoint, guard):
        guard()
        self.mutations += 1
        if self.fail_write:
            raise OperationError(Code.FAILED)
        if not self.false_success:
            self.volume = self.volume.model_copy(update={"percent": value})
        self.after_write()

    def set_mute(self, value, endpoint, guard):
        guard()
        self.mutations += 1
        if self.fail_write:
            raise OperationError(Code.FAILED)
        if not self.false_success:
            self.volume = self.volume.model_copy(update={"muted": value})
        self.after_write()

    def read_brightness(self):
        if self.fail_read:
            raise OperationError(Code.NO_OBSERVATION)
        return self.brightness

    def set_brightness(self, value, target, guard):
        guard()
        self.mutations += 1
        if self.fail_write:
            raise OperationError(Code.FAILED)
        if not self.false_success:
            self.brightness = self.brightness.model_copy(update={"percent": value})
        self.after_write()

    def capture(self, guard):
        from app.operations.capture import encode_header
        guard()
        self.mutations += 1
        self.after_write()
        return encode_header(2, 2) + bytes(16)


class FakeStore:
    def __init__(self):
        self.images = {}

    def save(self, data, *, guard):
        from uuid import uuid4
        from app.operations.capture import validate_bmp
        guard()
        validate_bmp(data)
        key = uuid4()
        self.images[key] = data
        return key

    def verify(self, key):
        from app.operations.capture import validate_bmp
        return validate_bmp(self.images[key])

    def exists(self, key):
        return key in self.images

    def delete(self, key, *, guard):
        guard()
        del self.images[key]
