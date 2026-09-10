"""Shared deterministic output gate. Never logs or repairs decoder content."""
import unicodedata

from app.stt.models import (
    SafeTranscriptionError, TranscriptionErrorCode as Code, TranscriptionStatus as Status,
)


class _Diagnostics:
    """Private bounded prefix only; default object repr never contains its contents."""
    __slots__ = ("_raw", "complete")

    def __init__(self, raw, complete):
        self._raw = raw[:8192]
        self.complete = complete and len(raw) <= 8192


class OutputBudget:
    """Bound generator consumption; acceptance rules remain in rejection_reasons."""
    def __init__(self, settings):
        self.settings = settings
        self.count = 0
        self.characters = 0
        self._prefix = ""
        self.exhausted = False

    def __repr__(self):
        return "<OutputBudget>"

    def add(self, text):
        self.count += 1
        self.characters += len(text)
        self._prefix += text[:max(0, 8192 - len(self._prefix))]
        self.exhausted = (self.count > self.settings.stt_safety_max_segments
                          or self.characters > self.settings.stt_safety_max_output_characters)
        return not self.exhausted

    def diagnostics(self):
        return _Diagnostics(self._prefix, not self.exhausted and self.characters <= 8192)


def _tokens(text):
    # Preserve Indic combining marks; punctuation creates boundaries rather than
    # joining words. This analysis never changes either public transcript field.
    return "".join(" " if unicodedata.category(c)[0] in "PZS" else c
                   for c in text.casefold()).split()


def rejection_reasons(result, settings):
    tokens = _tokens(result.text)
    reasons = []
    if not tokens:
        reasons.append("empty_output")
    if len(tokens) > max(settings.stt_safety_min_tokens,
                         settings.stt_safety_tokens_per_second * result.source_audio_duration):
        reasons.append("token_limit")
    if max(len(result.raw_transcript), len(result.text)) > max(
            settings.stt_safety_min_characters,
            settings.stt_safety_characters_per_second * result.source_audio_duration):
        reasons.append("character_limit")
    run = 0
    previous = None
    for token in tokens:
        run = run + 1 if token == previous else 1
        previous = token
        if run >= settings.stt_safety_word_repetitions:
            reasons.append("repeated_word")
            break
    for size in range(2, 9):
        found = False
        needed = max(settings.stt_safety_phrase_repetitions,
                     (settings.stt_safety_phrase_min_tokens + size - 1) // size)
        for start in range(len(tokens) - size * needed + 1):
            block = tokens[start:start + size]
            if all(tokens[start + size * i:start + size * (i + 1)] == block
                   for i in range(1, needed)):
                reasons.append("repeated_phrase")
                found = True
                break
        if found:
            break
    if any(s.no_speech_prob is not None and s.avg_logprob is not None
           and s.no_speech_prob >= settings.stt_safety_no_speech_prob
           and s.avg_logprob <= settings.stt_safety_avg_logprob
           for s in result.segments):
        reasons.append("no_speech")
    return tuple(reasons)


def reject(result, reasons, diagnostics=None):
    rejected = result.model_copy(update={
        "status": Status.UNUSABLE_AUDIO, "text": "", "segments": (),
        "language_probability": None, "error": SafeTranscriptionError(code=Code.UNUSABLE_AUDIO),
        "rejection_reasons": tuple(reasons),
    })
    rejected._diagnostics = diagnostics
    return rejected


def apply_output_safety(result, settings, cancel=None):
    """Fail closed for every engine; repeated application is safe."""
    if cancel is not None and cancel.is_set():
        cancelled = result.model_copy(update={
            "status": Status.CANCELLED, "text": "", "segments": (),
            "language_probability": None, "error": SafeTranscriptionError(code=Code.CANCELLED),
            "rejection_reasons": (),
        })
        cancelled._diagnostics = None
        return cancelled
    if result.status != Status.SUCCEEDED:
        if result.status != Status.UNUSABLE_AUDIO:
            result._diagnostics = None
        return result
    budget = OutputBudget(settings)
    try:
        for segment in result.segments:
            if not budget.add(segment.text):
                return reject(result, ("output_budget_exceeded",), budget.diagnostics())
        reasons = rejection_reasons(result, settings)
        return reject(result, reasons, budget.diagnostics()) if reasons else result
    except Exception:
        # Never stringify exceptions: validation/backend errors can embed text.
        return reject(result, ("safety_gate_error",), budget.diagnostics())
