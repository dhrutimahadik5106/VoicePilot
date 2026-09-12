"""Shared deterministic output gate. Never logs or repairs decoder content."""
import unicodedata
import math

from app.stt.models import (
    SafetySummary, SafetySegmentMetadata, SafeTranscriptionError, TranscriptionErrorCode as Code, TranscriptionStatus as Status,
)


class OutputBudget:
    """Bound generator consumption; acceptance rules remain in rejection_reasons."""
    def __init__(self, settings):
        self.settings = settings
        self.count = 0
        self.characters = 0
        self.exhausted = False
        self.token_count = 0
        self.normalized_characters = 0
        self.nonempty_segments = 0
        self.metadata = []

    def __repr__(self):
        return "<OutputBudget>"

    def add(self, text, segment=None):
        self.count += 1
        self.characters += len(text)
        self.exhausted = (self.count > self.settings.stt_safety_max_segments
                          or self.characters > self.settings.stt_safety_max_output_characters)
        if len(self.metadata) < 4096:
            self.metadata.append(SafetySegmentMetadata(
                no_speech_prob=_number(getattr(segment, "no_speech_prob", None), probability=True),
                avg_logprob=_number(getattr(segment, "avg_logprob", None)),
            ))
        if not self.exhausted:
            stripped = text.strip()
            self.normalized_characters += len(stripped)
            self.nonempty_segments += bool(stripped)
            self.token_count += len(_tokens(stripped))
        return not self.exhausted

    def summary(self, reasons, duration, duration_after_vad=None):
        return SafetySummary(
            rejection_reasons=tuple(reasons), actual_audio_duration=duration,
            original_segment_count=self.count,
            normalized_token_count=None if self.exhausted else self.token_count,
            character_count=max(self.characters, self.normalized_characters
                                + max(0, self.nonempty_segments - 1)),
            token_limit=max(self.settings.stt_safety_min_tokens,
                            self.settings.stt_safety_tokens_per_second * duration),
            character_limit=max(self.settings.stt_safety_min_characters,
                                self.settings.stt_safety_characters_per_second * duration),
            segment_metadata=tuple(self.metadata),
            duration_after_vad=_number(duration_after_vad, nonnegative=True),
            output_budget_exceeded=self.exhausted,
        )

def _number(value, *, probability=False, nonnegative=False):
    # Do not stringify arbitrary backend values or allow NaN/inf into JSON.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return None
    if not finite or (probability and not 0 <= value <= 1):
        return None
    if nonnegative and value < 0:
        return None
    return float(value)


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


def reject(result, reasons, summary=None):
    rejected = result.model_copy(update={
        "status": Status.UNUSABLE_AUDIO, "text": "", "segments": (),
        "language_probability": None, "error": SafeTranscriptionError(code=Code.UNUSABLE_AUDIO),
        "rejection_reasons": tuple(reasons), "safety_summary": summary,
    })
    rejected._diagnostics = None
    return rejected


def apply_output_safety(result, settings, cancel=None, *, duration_after_vad=None):
    """Fail closed for every engine; repeated application is safe."""
    if cancel is not None and cancel.is_set():
        cancelled = result.model_copy(update={
            "status": Status.CANCELLED, "text": "", "segments": (),
            "language_probability": None, "error": SafeTranscriptionError(code=Code.CANCELLED),
            "rejection_reasons": (), "safety_summary": None, "duration_after_vad": None,
        })
        cancelled._diagnostics = None
        return cancelled
    if result.status != Status.SUCCEEDED:
        if result.status != Status.UNUSABLE_AUDIO:
            result = result.model_copy(update={"safety_summary": None, "rejection_reasons": (), "duration_after_vad": None})
            result._diagnostics = None
        return result
    budget = OutputBudget(settings)
    try:
        for segment in result.segments:
            if not budget.add(segment.text, segment):
                return reject(result, ("output_budget_exceeded",),
                              budget.summary(("output_budget_exceeded",), result.source_audio_duration, duration_after_vad))
        reasons = rejection_reasons(result, settings)
        return reject(result, reasons,
                      budget.summary(reasons, result.source_audio_duration, duration_after_vad)) if reasons else result
    except Exception:
        # Never stringify exceptions: validation/backend errors can embed text.
        return reject(result, ("safety_gate_error",),
                      budget.summary(("safety_gate_error",), result.source_audio_duration, duration_after_vad))
