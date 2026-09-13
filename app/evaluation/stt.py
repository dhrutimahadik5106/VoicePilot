"""Paired private evaluation. C/D reuse A/B outputs; no medium implementation."""
import hashlib
import io
import platform
from collections import Counter
from importlib.metadata import version
from threading import Event
from time import perf_counter

import numpy as np

from app.commands.resolver import CommandResolver
from app.evaluation.dataset import EvaluationError, evidence_label, private_path, validate_manifest
from app.evaluation.metrics import Aggregate
from app.stt.context import load_vocabulary
from app.stt.parity import ComparisonEngine, ParitySettings
from app.stt.refinement import RULE_VERSION, refine
from app.stt.service import TranscriptionService, read_pcm_wav_stream


def private_audio_loader(root, max_duration):
    def load(row):
        try:
            path = private_path(root, row.audio)
            limit = int(48000 * 8 * 4 * max_duration + 65536)
            if path.stat().st_size > limit: raise ValueError()
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
            if len(data) > limit or hashlib.sha256(data).hexdigest() != row.audio_sha256:
                raise ValueError()
            with io.BytesIO(data) as buffer:
                return read_pcm_wav_stream(buffer, max_duration)
        except Exception:
            raise EvaluationError("invalid_private_audio") from None
    return load


def run_evaluation(manifest, settings, *, audio_loader, engine_factory=ComparisonEngine,
                   vocabulary=None, overlay=None, include_utterances=False, cancel=None,
                   private_root=None, language_mode="manifest"):
    """Caller must validate real manifests/root/consent before authorizing audio access."""
    if settings.whisper_model != "small":
        raise EvaluationError("only_small_approved_medium_is_placeholder")
    cancel = cancel if cancel is not None else Event()
    vocabulary = vocabulary if vocabulary is not None else load_vocabulary()
    if language_mode not in {"manifest", "auto"}:
        raise EvaluationError("invalid_language_mode")
    validate_manifest(manifest, root=private_root, public_vocabulary=vocabulary)
    common = settings.model_dump() | {"stt_local_files_only": True, "stt_initial_prompt": "", "stt_hotwords": ""}
    snapshots = {arm: ParitySettings.model_validate(common | {"stt_contextual_enabled": arm == "B"}) for arm in ("A", "B")}
    engines, aggregates, utterances = {}, {}, []
    resolver = CommandResolver.from_directory()
    results = {}
    source = None
    context_statuses = Counter()
    try:
        for arm in ("A", "B"):
            engines[arm] = engine_factory(snapshots[arm], context=vocabulary, overlay=overlay)
        for index, row in enumerate(manifest.rows):
            if cancel.is_set(): return {"status": "cancelled"}
            source = audio_loader(row)
            # Alternate order across recordings; no extra decoding for C/D.
            order = ("A", "B") if index % 2 == 0 else ("B", "A")
            for arm in order:
                engines[arm]._path = arm
                language = None if row.language == "mixed" or language_mode == "auto" else row.language
                # Explicit settings language enables a separate fixed-language experiment.
                language = settings.stt_language if settings.stt_language is not None else language
                results[arm] = TranscriptionService(snapshots[arm], engines[arm]).transcribe_audio(
                    source, language=language or "auto", cancel=cancel)
                if cancel.is_set() or results[arm].status == "cancelled": return {"status": "cancelled"}
            context_statuses[engines["B"].context_status] += 1
            left, right = engines["A"]._prepared.get("A"), engines["B"]._prepared.get("B")
            if left is None or right is None or not np.array_equal(left, right):
                raise EvaluationError("prepared_audio_not_identical")
            start = perf_counter()
            refined = refine(results["B"])
            refinement_seconds = perf_counter() - start
            for arm in ("A", "B", "C"):
                result = results["B" if arm == "C" else arm]
                text = (refined.refined_transcript or result.raw_transcript) if arm == "C" else None
                for group in ("overall", row.language):
                    aggregate = aggregates.setdefault((arm, group), Aggregate())
                    aggregate.observe(row, result, hypothesis=text,
                                      refinement_seconds=refinement_seconds if arm == "C" else 0)
            for arm in ("A", "B"):
                proposal = None
                if row.task == "command":
                    proposal = (resolver.resolve_stt(results[arm]) if results[arm].status != "succeeded" or len(results[arm].raw_transcript) <= 500
                                else resolver.resolve(""))
                for group in ("overall", row.language):
                    aggregate = aggregates.setdefault(("D_from_" + arm, group), Aggregate())
                    aggregate.observe(row, results[arm], proposal=proposal)
            if include_utterances:
                utterances.append({"recording_id": row.recording_id, "ground_truth": row.ground_truth,
                                   "A": results["A"].raw_transcript if results["A"].status == "succeeded" else "",
                                   "B": results["B"].raw_transcript if results["B"].status == "succeeded" else "",
                                   "shadow": refined.inspection()})
            for engine in engines.values(): engine.discard()
            results.clear()
            source = left = right = refined = proposal = result = text = None
        report = {"status": "completed", "evidence": evidence_label(manifest.rows),
                  "metadata": {"split_counts": dict(Counter(r.split for r in manifest.rows)),
                    "evaluation_scope": "pooled_splits_not_held_out_score" if len({r.split for r in manifest.rows}) > 1 else manifest.rows[0].split,
                    "model": "small", "model_reference": "Systran/faster-whisper-small",
                    "model_revision": "unavailable_not_claimed", "faster_whisper_version": version("faster-whisper"),
                    "hardware": {"device": settings.whisper_device, "compute_type": settings.whisper_compute_type,
                                 "os": platform.system(), "architecture": platform.machine()},
                    "language_mode": settings.stt_language or ("auto" if language_mode == "auto" else "manifest_language_mixed_auto"),
                    "decoding": {"beam_size": settings.stt_beam_size, "temperature": settings.stt_temperature,
                                 "condition_on_previous_text": "backend_default_true", "word_timestamps": settings.stt_word_timestamps},
                    "vad": {"enabled": settings.stt_vad_filter, "min_silence_duration_ms": settings.stt_vad_min_silence_duration_ms,
                            "speech_pad_ms": 400},
                    "safety": {k: v for k, v in settings.model_dump().items() if k.startswith("stt_safety_")},
                    "vocabulary_version": vocabulary.version, "private_overlay_used": overlay is not None,
                    "refinement_version": RULE_VERSION, "context_status": engines["B"].context_status,
                    "context_status_counts": dict(context_statuses),
                    "prepared_inputs_equal": True},
                  "arms": {arm: {group: aggregate.report() for (a, group), aggregate in aggregates.items() if a == arm}
                           for arm in ("A", "B", "C", "D_from_A", "D_from_B")},
                  "E": {"implemented": False, "requires_separate_approval_and_download": True}}
        if include_utterances: report["utterances"] = utterances
        return {"status": "cancelled"} if cancel.is_set() else report
    except (KeyboardInterrupt, InterruptedError):
        cancel.set()
        return {"status": "cancelled"}
    except Exception:
        raise EvaluationError("evaluation_failed") from None
    finally:
        source = left = right = refined = proposal = result = text = None
        results.clear()
        for engine in engines.values(): engine.close()
        # No manifest/audio/transcript history is retained by this module.
