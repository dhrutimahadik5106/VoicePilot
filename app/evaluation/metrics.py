"""Bounded edit scoring on temporary NFC/casefold/punctuation-separated copies."""
import unicodedata
import numpy as np


def normalized(text):
    text = unicodedata.normalize("NFC", text).casefold()
    return " ".join("".join(" " if unicodedata.category(c).startswith("P") else c for c in text).split())


def distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def fraction(numerator, denominator, samples=0):
    return {"numerator": numerator, "denominator": denominator,
            "percentage": 100 * numerator / denominator if denominator else None, "sample_count": samples}


def text_counts(reference, hypothesis):
    ref, hyp = normalized(reference), normalized(hypothesis)
    rc, hc = ref.replace(" ", ""), hyp.replace(" ", "")
    result = {"wer": (distance(ref.split(), hyp.split()), len(ref.split())),
              "cer": (distance(rc, hc), len(rc)),
              "whitespace_sensitive_cer": (distance(ref, hyp), len(ref))}
    if rc == hc:
        def boundaries(text):
            offset, positions = 0, set()
            for c in text:
                if c == " ": positions.add(offset)
                else: offset += 1
            return positions
        result["boundary_error"] = (len(boundaries(ref) ^ boundaries(hyp)), max(0, len(rc) - 1))
    return result


class Aggregate:
    def __init__(self):
        names = [prefix + metric for prefix in ("delivered_", "accepted_")
                 for metric in ("wer", "cer", "whitespace_sensitive_cer", "boundary_error")]
        names += ["successful_stt_coverage", "false_rejection", "non_speech_rejection",
                  "successful_spurious_output", "transcription_failure", "empty_reference_word_insertions"]
        self.counts = {name: (0, 0, 0) for name in names}
        self.samples = 0
        self.audio_seconds = 0.0
        self.inference = []
        self.processing = []
        self.rtf = []
        self.cold = 0
        self.warm = 0
        self.refinement_time = []

    def add(self, key, numerator, denominator=1):
        n, d, samples = self.counts.get(key, (0, 0, 0))
        self.counts[key] = (n + numerator, d + denominator, samples + 1)

    def observe(self, row, result, *, hypothesis=None, proposal=None, refinement_seconds=0):
        self.samples += 1
        self.audio_seconds += result.source_audio_duration
        succeeded = result.status == "succeeded"
        text = result.raw_transcript if hypothesis is None and succeeded else hypothesis or ""
        if not succeeded:
            text = ""
        for name, (n, d) in text_counts(row.ground_truth, text).items():
            self.add("delivered_" + name, n, d)
            if succeeded:
                self.add("accepted_" + name, n, d)
        self.add("successful_stt_coverage", succeeded)
        if not row.ground_truth:
            self.add("empty_reference_word_insertions", len(normalized(text).split()), 0)
        if row.usable_speech:
            self.add("false_rejection", result.status == "unusable_audio")
        if row.content == "non_speech":
            self.add("non_speech_rejection", result.status == "unusable_audio")
            self.add("successful_spurious_output", succeeded and bool(normalized(text)))
        self.add("transcription_failure", result.status == "failed")
        if row.task == "command" and proposal is not None:
            intent_ok = proposal.intent == row.expected_intent
            entities_ok = proposal.entities == row.expected_entities
            canonical_ok = proposal.canonical_command == row.expected_canonical
            correct = intent_ok and entities_ok and canonical_ok
            accepted = succeeded and proposal.status == "resolved" and not proposal.requires_confirmation
            unsafe = row.expected_confirmation or row.expected_intent is None or not correct
            self.add("intent_accuracy", intent_ok)
            self.add("exact_entity_accuracy", entities_ok)
            self.add("canonical_command_accuracy", canonical_ok)
            self.add("confirmation_rate", proposal.requires_confirmation)
            self.add("acceptance_coverage", accepted)
            self.add("unsafe_false_accept_rate", accepted and unsafe, int(unsafe))
            self.add("false_accept_among_accepted", accepted and unsafe, int(accepted))
            for slot in {"application", "media"}:
                if slot in row.expected_entities or slot in proposal.entities:
                    self.add("slot_" + slot + "_accuracy", proposal.entities.get(slot) == row.expected_entities.get(slot))
        self.inference.append(result.inference_duration)
        self.processing.append(result.processing_duration)
        if result.real_time_factor is not None: self.rtf.append(result.real_time_factor)
        self.cold += result.cold_start is True
        self.warm += result.cold_start is False
        self.refinement_time.append(refinement_seconds)

    def report(self):
        def timing(values):
            return {"sample_count": len(values), "total": float(sum(values)),
                    "mean": float(np.mean(values)) if values else None,
                    "p50": float(np.percentile(values, 50)) if values else None,
                    "p95": float(np.percentile(values, 95)) if values else None}
        return {"sample_count": self.samples, "source_audio_seconds": self.audio_seconds,
                "weighted_rtf": sum(self.processing) / self.audio_seconds if self.audio_seconds else None, "metrics": {k: fraction(*v) for k, v in sorted(self.counts.items())},
                "inference_seconds": timing(self.inference), "processing_seconds": timing(self.processing),
                "rtf": timing(self.rtf), "refinement_seconds": timing(self.refinement_time),
                "cold_count": self.cold, "warm_count": self.warm}
