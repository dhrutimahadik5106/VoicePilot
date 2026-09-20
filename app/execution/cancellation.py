"""Process-local cooperative cancellation. No OS process control or IPC."""
from contextlib import contextmanager
from threading import Event, Lock


class CancellationHub:
    def __init__(self):
        self._lock = Lock()
        self._active = {}
        self.stopped = Event()

    @contextmanager
    def track(self, event):
        with self._lock:
            self._active[event] = self._active.get(event, 0) + 1
            if self.stopped.is_set():
                event.set()
        try:
            yield event
        finally:
            with self._lock:
                remaining = self._active[event] - 1
                if remaining:
                    self._active[event] = remaining
                else:
                    del self._active[event]

    def cancel(self, *, emergency=False):
        with self._lock:
            if emergency:
                self.stopped.set()
            count = len(self._active)
            for event in self._active:
                event.set()
            return count


GLOBAL = CancellationHub()


class CallbackSignal:
    def __init__(self, callback):
        self.callback = callback

    def set(self):
        self.callback()


class CombinedSignal:
    """Hub-owned cancellation plus an optional caller-owned signal."""

    def __init__(self, caller):
        self.caller = caller
        self.local = Event()

    def set(self):
        self.local.set()
        setter = getattr(self.caller, "set", None)
        if callable(setter):
            setter()

    def is_set(self):
        return self.local.is_set() or (self.caller is not None and self.caller.is_set())


def cooperative(method):
    """Register existing keyword-only cancellation contracts without starting work."""
    from functools import wraps
    @wraps(method)
    def wrapped(*args, **kwargs):
        signal = kwargs.get("cancel")
        if not isinstance(signal, CombinedSignal):
            signal = CombinedSignal(signal)
        kwargs["cancel"] = signal
        with GLOBAL.track(signal):
            return method(*args, **kwargs)
    return wrapped
