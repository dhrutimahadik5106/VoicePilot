"""Synthetic segment-boundary regression; no private recordings or records."""
from types import SimpleNamespace

import pytest

from app.owner.challenge import PHRASES
from app.owner.models import OwnerError
from app.stt.models import TranscriptSegment, TranscriptionResult
from app.stt.service import TranscriptionService


class SegmentEngine:
    def __init__(self, parts):
        self.parts = parts
        self.results = []

    def transcribe(self, request, *, cancel=None):
        result = TranscriptionResult(
            audio_id=request.audio_id,
            text=" ".join(part.strip() for part in self.parts if part.strip()),
            segments=tuple(TranscriptSegment(text=part, start=i, end=i + 1)
                           for i, part in enumerate(self.parts)),
            language="en", processing_duration=.1,
            source_audio_duration=request.audio.duration,
            model_name="synthetic", device="cpu", compute_type="int8", status="succeeded",
        )
        self.results.append(result)
        return result


@pytest.mark.parametrize("index,parts", [
    (1, ("Seven bright flowers grow near", "the little wooden gate.")),
    (11, ("The orange basket holds several fresh", "apples and pears.")),
])
def test_owner_uses_segment_boundary_normalization(harness, index, parts):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.phrase_counter = index
    engine = SegmentEngine(parts)
    harness.calibration.stt = TranscriptionService(harness.settings, engine)
    result = harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert result["owner_count"] == 1
    assert engine.results[0].raw_transcript == "".join(parts)
    assert engine.results[0].normalized_transcript == PHRASES[index] + "."
    assert harness.backend.mutations == harness.launch_backend.launched == 0


@pytest.mark.parametrize("text", [
    PHRASES[1] + ".", "  " + PHRASES[1] + "  ",
    PHRASES[1].replace(" ", "   "), PHRASES[1].upper(),
    PHRASES[1].replace(" ", "\u00a0"), "\t" + PHRASES[1] + "!\r\n",
    PHRASES[1] + "?", PHRASES[1] + "...",
])
def test_safe_canonical_equivalence(text):
    from app.owner.challenge import Challenges
    from app.owner.models import Configuration
    Challenges(Configuration()).verify(PHRASES[1], text)


def test_unicode_canonical_normalization():
    from app.owner.challenge import normalize_phrase, NORMALIZATION_VERSION
    assert NORMALIZATION_VERSION == "owner-phrase-normalization-v1"
    assert normalize_phrase("Cafe\u0301.") == normalize_phrase("CAF\u00c9")


@pytest.mark.parametrize("text", [
    "Seven flowers grow near the little wooden gate",
    PHRASES[1] + " please", "Bright seven flowers grow near the little wooden gate",
    "Seven bright flowers", "open notepad", "Seven bright flowers grow near the little wooden gait",
    "Seven bright flowers grow nearthe little wooden gate", PHRASES[1].replace("bright", "bri.ght"),
    PHRASES[1].replace("bright", "bri\u200bght"), PHRASES[1] + "\x1b[31m", "", None,
])
def test_non_equivalent_phrases_fail_closed(text):
    from app.owner.challenge import Challenges
    from app.owner.models import Configuration
    with pytest.raises(OwnerError, match="phrase_mismatch"):
        Challenges(Configuration()).verify(PHRASES[1], text)


@pytest.mark.parametrize("fault", ["fused", "spaces", "hidden", "duplicate", "order", "missing", "punctuation"])
def test_corpus_validation_rejects_malformed_entries(fault):
    from app.owner.challenge import validate_corpus
    phrases = list(PHRASES)
    if fault == "fused":
        phrases[-1] = phrases[-1].replace("fresh apples", "freshapples")
    elif fault == "spaces":
        phrases[-1] = phrases[-1].replace("fresh apples", "fresh  apples")
    elif fault == "hidden":
        phrases[-1] += "\u200b"
    elif fault == "duplicate":
        phrases[-1] = phrases[0]
    elif fault == "order":
        phrases.reverse()
    elif fault == "missing":
        phrases.pop()
    else:
        phrases[-1] += "."
    with pytest.raises(OwnerError, match="phrase_mismatch"):
        validate_corpus(tuple(phrases))


def test_fresh_apples_corpus_is_exact_and_validated_at_construction(monkeypatch):
    import app.owner.challenge as module
    from app.owner.models import Configuration
    assert PHRASES[-1] == "The orange basket holds several fresh apples and pears"
    module.validate_corpus()
    monkeypatch.setattr(module, "PHRASES", (*PHRASES[:-1], PHRASES[-1].replace("fresh apples", "freshapples")))
    with pytest.raises(OwnerError):
        module.Challenges(Configuration())


def test_diagnostic_and_owner_segment_normalization_parity(harness, monkeypatch):
    from app.pipeline.service import DiagnosticService
    from app.pipeline.models import Trace
    from app.owner.challenge import normalize_phrase

    parts = ("Seven bright flowers grow near", "the little wooden gate.")
    engine = SegmentEngine(parts)
    stt = TranscriptionService(harness.settings, engine)
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.phrase_counter = 1
    harness.calibration.stt = stt
    harness.calibration.collect(key, "owner", "quiet", consent=True)
    seen = []
    diagnostic = DiagnosticService(harness.settings, stt=stt, resolver=object())

    def finish(raw, normalized, base, cancel):
        seen.append((raw, normalized))
        return Trace(**base, status="blocked", reason="unsupported_command")

    monkeypatch.setattr(diagnostic, "_finish", finish)
    trace = diagnostic.audio(harness.last_audio)
    assert trace.stt_status == "succeeded" and not trace.execution_permitted
    assert seen == [("".join(parts), " ".join(parts))]
    assert normalize_phrase(seen[0][1]) == normalize_phrase(PHRASES[1])
    assert harness.backend.mutations == harness.launch_backend.launched == 0


def test_seven_existing_style_samples_resume_without_migration(harness):
    import json
    from app.owner.cli import main
    from app.owner.models import Record

    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    for i in range(7):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    before = harness.store.load(key).document()
    # Round-trip the existing schema as a restart would; no real store is opened.
    restored = Record.model_validate(json.loads(json.dumps(before)))
    harness.store.records[key] = restored.document()
    output = []
    runtime = SimpleNamespace(calibration=lambda: harness.calibration)
    assert main(["resume", "--profile", str(key)], settings=harness.settings,
                factory=lambda *a, **k: runtime, interactive=lambda: True,
                write=output.append) == 0
    assert json.loads(output[-1])["owner_count"] == 7
    assert harness.store.load(key).document() == before
    harness.phrase_wrong = True
    with pytest.raises(OwnerError, match="phrase_mismatch"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.store.load(key).document() == before
    harness.phrase_counter = 11
    harness.calibration.stt = TranscriptionService(harness.settings, SegmentEngine(
        ("The orange basket holds several fresh", "apples and pears.")))
    result = harness.calibration.collect(key, "owner", "different_environment", consent=True)
    assert result["owner_count"] == 8 and result["state"] == "owner_validation_complete"
    after = harness.store.load(key).document()
    for field in ("provenance", "configuration", "model", "profile", "consent", "created_at"):
        assert after["private"][field] == before["private"][field]
    for field in ("digests", "captures", "sessions"):
        assert after["private"][field][:7] == before["private"][field]
    assert harness.backend.mutations == harness.launch_backend.launched == 0


def test_phrase_mismatch_never_executes_or_leaks(calibrated, capsys, caplog):
    calibrated.phrase_wrong = True
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.reason == "phrase_mismatch"
    assert calibrated.capture_count == calibrated.stt_calls == 1
    assert calibrated.backend.mutations == calibrated.launch_backend.launched == 0
    public = result.model_dump_json() + repr(result) + capsys.readouterr().out + caplog.text
    assert "unrelated private marker" not in public
    assert not any(phrase in public for phrase in PHRASES)
    record = calibrated.store.load(calibrated.profile.profile_id)
    assert "unrelated private marker" not in str(record.document())
    assert not any(phrase in str(record.document()) for phrase in PHRASES)


def test_fused_word_inside_single_segment_is_not_repaired(harness):
    key = harness.profile.profile_id
    harness.calibration.begin(key, consent=True)
    harness.phrase_counter = 11
    harness.calibration.stt = TranscriptionService(harness.settings, SegmentEngine(
        (PHRASES[-1].replace("fresh apples", "freshapples"),)))
    with pytest.raises(OwnerError, match="phrase_mismatch"):
        harness.calibration.collect(key, "owner", "quiet", consent=True)
    assert harness.calibration.status(key)["owner_count"] == 0



def test_runtime_and_diagnostic_use_identical_stt_settings(harness, monkeypatch):
    from uuid import uuid4
    from app.owner.runtime import Runtime
    from app.pipeline.service import DiagnosticService
    from app.pipeline.models import Trace
    import app.stt.faster_whisper_engine as engine_module

    configured = []
    def factory(settings):
        configured.append(settings.model_dump())
        return SegmentEngine((PHRASES[1] + ".",))

    monkeypatch.setattr(engine_module, "FasterWhisperEngine", factory)
    audio = harness.capture(PHRASES[1], uuid4(), uuid4(), guard=lambda: None)
    runtime = Runtime(harness.settings, write=lambda _: None)
    owner_result = runtime.transcribe_audio(audio, audio_id=uuid4())
    diagnostic = DiagnosticService(harness.settings, resolver=object())
    monkeypatch.setattr(diagnostic, "_finish", lambda raw, normalized, base, cancel:
                        Trace(**base, status="blocked", reason="unsupported_command"))
    trace = diagnostic.audio(audio)
    assert owner_result.status == trace.stt_status == "succeeded"
    assert len(configured) == 2 and configured[0] == configured[1]
    assert configured[0]["stt_local_files_only"] is True
