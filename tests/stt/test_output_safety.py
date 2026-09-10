"""Synthetic policy fixtures only; never use microphone, network or a model."""
from threading import Event
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.stt import output_safety
from app.stt.cli import display_result
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.models import TranscriptSegment, TranscriptionRequest, TranscriptionResult
from app.stt.service import TranscriptionService
from tests.stt import FakeModel, audio, isolated_stt, segment


def result(text, seconds=6.72, **metadata):
    return TranscriptionResult(
        audio_id=uuid4(), text=text.strip(), language="en",
        segments=(TranscriptSegment(text=text, start=0, end=seconds, **metadata),),
        processing_duration=1, source_audio_duration=seconds,
        model_name="small", device="cpu", compute_type="int8", status="succeeded",
    )


def gate(text, seconds=6.72, **metadata):
    return output_safety.apply_output_safety(result(text, seconds, **metadata), Settings())


@pytest.mark.parametrize("text", [
    "Hey Voice Pilot, open Spotify and play Taare Zameen Par.",
    "stop, stop", "STOP! stop.", "Spotify खोलो", "स्पॉटिफाय उघडा",
    "VoicePilot Spotify वर गाणे लाव", "कृपया गाना चलाओ",
])
def test_normal_multilingual_commands_unchanged(text):
    original = result("  " + text + "  ")
    accepted = output_safety.apply_output_safety(original, Settings())
    assert accepted.status == "succeeded"
    assert accepted.raw_transcript == "  " + text + "  "
    assert accepted.text == text


@pytest.mark.parametrize("count,rejected", [(7, False), (8, True), (9, True)])
def test_identical_word_boundary(count, rejected):
    checked = gate("Google, " * count)
    assert ("repeated_word" in checked.rejection_reasons) is rejected


@pytest.mark.parametrize("phrase,count,rejected", [
    ("one two", 7, False), ("one two", 8, True),
    ("one two three", 5, False), ("one two three", 6, True),
    ("one two three four", 3, False), ("one two three four", 4, True),
    ("one two three four five six seven eight", 4, True),
])
def test_phrase_boundaries(phrase, count, rejected):
    checked = gate((phrase + " ") * count, seconds=30)
    assert ("repeated_phrase" in checked.rejection_reasons) is rejected


@pytest.mark.parametrize("seconds,count,rejected", [(1,30,False),(1,31,True),(10,60,False),(10,61,True)])
def test_token_limit(seconds, count, rejected):
    checked = gate(" ".join(str(i) for i in range(count)), seconds)
    assert ("token_limit" in checked.rejection_reasons) is rejected


@pytest.mark.parametrize("seconds,count,rejected", [(1,180,False),(1,181,True),(10,400,False),(10,401,True)])
def test_character_limit(seconds, count, rejected):
    assert ("character_limit" in gate("x" * count, seconds).rejection_reasons) is rejected


@pytest.mark.parametrize("prob,logprob,rejected", [
    (.8,-1,True), (.9,-2,True), (.799,-1,False), (.8,-.999,False),
    (None,-2,False), (.9,None,False),
])
def test_joint_no_speech_evidence(prob, logprob, rejected):
    assert ("no_speech" in gate("hello", no_speech_prob=prob,
                              avg_logprob=logprob).rejection_reasons) is rejected


@pytest.mark.parametrize("text", ["", "  ", "..."])
def test_empty_output_rejected(text):
    assert gate(text).status == "unusable_audio"


def test_synthetic_reconstruction_privacy(caplog, tmp_path):
    # Synthetic reconstruction: original 6.72s audio/decoder metadata not retained.
    text = "Google Facebook " * 60
    checked = gate(text)
    assert checked.status == "unusable_audio"
    assert checked.raw_transcript == checked.normalized_transcript == checked.text == ""
    assert checked.segments == ()
    assert checked._diagnostics._raw == text
    assert checked._diagnostics.complete
    output = []
    assert display_result(checked, output.append) == 1
    for rendered in (repr(checked), str(checked), repr(checked._diagnostics),
                     checked.model_dump_json(), str(checked.model_dump()), str(output), caplog.text):
        assert "Google" not in rendered and "Facebook" not in rendered
    assert list(tmp_path.iterdir()) == []


def test_exception_is_safe(monkeypatch):
    def broken(*args):
        raise ValueError("private transcript Google Facebook")
    monkeypatch.setattr(output_safety, "rejection_reasons", broken)
    checked = gate("private transcript Google Facebook")
    assert checked.rejection_reasons == ("safety_gate_error",)
    assert checked.raw_transcript == ""
    assert "private transcript" not in checked.model_dump_json()


def test_cancellation_discards_private_diagnostics():
    rejected = gate("Google " * 8)
    cancel = Event()
    cancel.set()
    checked = output_safety.apply_output_safety(rejected, Settings(), cancel)
    assert checked.status == "cancelled"
    assert checked._diagnostics is None and checked.raw_transcript == ""


@pytest.mark.parametrize("kind", ["characters", "segments"])
def test_generator_budget_closes_and_bounds_diagnostics(kind):
    settings = Settings(stt_safety_max_segments=2)
    segments = [segment("x" * 9000)] if kind == "characters" else [segment("hello")] * 3
    model = FakeModel(segments)
    engine = FasterWhisperEngine(settings, model_factory=lambda *a, **kw: model)
    checked = engine.transcribe(TranscriptionRequest(audio=audio()))
    assert checked.rejection_reasons == ("output_budget_exceeded",)
    assert checked.status == "unusable_audio" and checked.text == ""
    assert len(checked._diagnostics._raw) <= 8192
    assert not checked._diagnostics.complete
    assert model.closed


def test_engine_retains_no_speech_metadata():
    item = segment(" hello")
    item.no_speech_prob = .8
    item.avg_logprob = -1
    model = FakeModel([item])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    assert checked.rejection_reasons == ("no_speech",)


def test_every_engine_is_gated_using_actual_audio_duration():
    class AlternateEngine:
        def transcribe(self, request, cancel=None):
            return result(" ".join(str(i) for i in range(40)), seconds=120)
    checked = TranscriptionService(Settings(), AlternateEngine()).transcribe_audio(audio())
    assert "token_limit" in checked.rejection_reasons
    assert checked.source_audio_duration == 1


def test_policy_is_idempotent_and_configurable():
    original = result("stop " * 8, seconds=10)
    settings = Settings(stt_safety_word_repetitions=9)
    assert output_safety.apply_output_safety(original, settings).status == "succeeded"
    rejected = gate("stop " * 8)
    assert output_safety.apply_output_safety(rejected, Settings()) is rejected


def test_low_language_probability_alone_does_not_reject():
    original = result("hello").model_copy(update={"language_probability": .001})
    assert output_safety.apply_output_safety(original, Settings()).status == "succeeded"


def test_endless_generator_stops_after_bounded_consumption():
    from types import SimpleNamespace
    counts = []
    closed = []
    class EndlessModel:
        supported_languages = ["en"]
        def transcribe(self, *args, **kwargs):
            def stream():
                try:
                    while True:
                        counts.append(1)
                        yield segment("")
                finally:
                    closed.append(True)
            return stream(), SimpleNamespace(language="en", language_probability=.5)
    checked = FasterWhisperEngine(Settings(stt_safety_max_segments=3),
        model_factory=lambda *a, **kw: EndlessModel()).transcribe(TranscriptionRequest(audio=audio()))
    assert checked.rejection_reasons == ("output_budget_exceeded",)
    assert len(counts) == 4 and closed == [True]


def test_repetition_across_segments_keeps_exact_private_decoder_output():
    model = FakeModel([segment(" Google") for _ in range(8)])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    assert "repeated_word" in checked.rejection_reasons
    assert checked._diagnostics._raw == " Google" * 8
    assert checked.raw_transcript == ""


def test_empty_engine_output_is_unusable():
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: FakeModel([])).transcribe(
        TranscriptionRequest(audio=audio()))
    assert checked.status == "unusable_audio"
    assert checked.rejection_reasons == ("empty_output",)


def test_alternate_engine_budget_and_cancellation():
    class Alternate:
        def transcribe(self, request, cancel=None):
            if cancel is not None:
                cancel.set()
            return result("x" * 9000)
    service = TranscriptionService(Settings(), Alternate())
    checked = service.transcribe_audio(audio())
    assert checked.rejection_reasons == ("output_budget_exceeded",)
    assert len(checked._diagnostics._raw) == 8192
    cancelled = service.transcribe_audio(audio(), cancel=Event())
    assert cancelled.status == "cancelled" and cancelled._diagnostics is None


def test_environment_threshold_configuration(monkeypatch):
    monkeypatch.setenv("VOICEPILOT_STT_SAFETY_WORD_REPETITIONS", "9")
    assert Settings().stt_safety_word_repetitions == 9


@pytest.mark.parametrize("field,value", [
    ("stt_safety_word_repetitions", 1),
    ("stt_safety_phrase_repetitions", 0),
    ("stt_safety_tokens_per_second", float("nan")),
    ("stt_safety_characters_per_second", float("inf")),
    ("stt_safety_no_speech_prob", 1.1),
    ("stt_safety_avg_logprob", 1),
    ("stt_safety_max_segments", 0),
    ("stt_safety_max_output_characters", 0),
])
def test_invalid_threshold_configuration(field, value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_private_diagnostics_preserve_decoder_order():
    first, second = segment(" later", 1, 2), segment(" earlier", 0, 1)
    first.no_speech_prob, first.avg_logprob = .9, -2
    model = FakeModel([first, second])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio(3)))
    assert checked.status == "unusable_audio"
    assert checked._diagnostics._raw == " later earlier"


def test_no_speech_evidence_must_belong_to_same_segment():
    original = result("hello world").model_copy(update={
        "segments": (TranscriptSegment(text="hello ", start=0, end=1, no_speech_prob=.9),
                     TranscriptSegment(text="world", start=1, end=2, avg_logprob=-2)),
    })
    assert output_safety.apply_output_safety(original, Settings()).status == "succeeded"
