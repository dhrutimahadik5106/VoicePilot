"""Opt-in bounded numerical diagnostics. Never a deadline or authorization clock."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from math import isfinite
from time import perf_counter

STAGES = frozenset({
    "runtime_initialization", "challenge_preparation", "challenge_speaker_inference", "challenge_phrase_verification",
    "confirmation_enter_wait", "confirmation_capture", "confirmation_recording",
    "command_recording", "command_speaker_inference", "confirmation_speaker_inference",
    "confirmation_stt", "authorization", "total_session",
    "consent_to_phrase_display", "phrase_display_to_enter", "command_enter_wait",
    "recorder_setup", "capture", "command_capture", "challenge_total",
    "speaker_model_load", "speaker_integrity", "speaker_inference", "phrase_stt", "command_stt",
    "stt_model_load", "stt_inference", "planning", "execution",
    "observation", "verification", "controller_total", "total_after_consent",
})
TEMPERATURES = frozenset({"cold", "warm", "not_applicable"})
_ACTIVE = ContextVar("numerical_timing_report", default=None)
LIMIT = 128


class Report:
    def __init__(self, *, clock=perf_counter):
        self.clock = clock
        self._rows = []
        self._starts = {}
        self.dropped = 0

    def now(self):
        try:
            value = self.clock()
            return value if type(value) in (float, int) and isfinite(value) else None
        except Exception:
            return None

    def add(self, stage, seconds, temperature="not_applicable", completed=True):
        if (type(stage) is not str or stage not in STAGES or type(temperature) is not str
                or temperature not in TEMPERATURES or type(completed) is not bool
                or type(seconds) not in (int, float) or not isfinite(seconds) or not 0 <= seconds <= 3600):
            self.dropped = min(LIMIT, self.dropped + 1)
            return
        row = {"stage": stage, "seconds": float(seconds),
               "temperature": temperature, "completed": completed}
        if len(self._rows) >= LIMIT:
            self.dropped = min(LIMIT, self.dropped + 1)
            if stage == "total_after_consent":
                self._rows[-1] = row  # Preserve total latency even if bounded polling fills the report.
            return
        self._rows.append(row)

    def document(self):
        return {"label": "opt_in_numerical_timings", "unit": "seconds",
                "samples": [dict(row) for row in self._rows], "dropped": self.dropped}


def activate(report):
    return _ACTIVE.set(report)


def deactivate(token):
    report = _ACTIVE.get()
    if report is not None:
        report._starts.clear()
    _ACTIVE.reset(token)


def add(stage, seconds, temperature="not_applicable"):
    report = _ACTIVE.get()
    if report is not None:
        report.add(stage, seconds, temperature)


def begin(stage):
    report = _ACTIVE.get()
    if report is not None and stage in STAGES:
        report._starts[stage] = report.now()


def end(stage):
    report = _ACTIVE.get()
    if report is not None:
        start = report._starts.pop(stage, None)
        finish = report.now()
        if start is not None and finish is not None:
            report.add(stage, finish - start)


@contextmanager
def span(stage, temperature="not_applicable"):
    report = _ACTIVE.get()
    start = report.now() if report is not None else None
    completed = False
    try:
        yield
        completed = True
    finally:
        if report is not None:
            finish = report.now()
            if start is not None and finish is not None:
                report.add(stage, finish - start, temperature, completed)


def timed(stage):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            if _ACTIVE.get() is None:
                return function(*args, **kwargs)
            with span(stage):
                return function(*args, **kwargs)
        return measured
    return decorate
