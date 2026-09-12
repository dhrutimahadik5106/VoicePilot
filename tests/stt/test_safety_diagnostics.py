"""Numerical-only observability; all decoder and capture inputs are synthetic."""
import json
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.stt.cli import display_result, main
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.models import SafetySummary, TranscriptionRequest
from app.stt.output_safety import apply_output_safety
from app.stt.service import TranscriptionService
from tests.stt import FakeModel, audio, isolated_stt, segment
from tests.stt.test_cli import FakeRecorder
from tests.stt.test_output_safety import result

SECRET = "UNIQUE_PRIVATE_9c23_DIAGNOSTIC_SECRET"


def rejected():
    return apply_output_safety(result(SECRET, no_speech_prob=.9, avg_logprob=-2),
                               Settings(), duration_after_vad=4.5)


def test_summary_before_sanitization():
    checked = rejected()
    summary = checked.safety_summary
    assert checked.text == checked.raw_transcript == "" and checked.segments == ()
    assert summary.rejection_reasons == ("no_speech",)
    assert summary.original_segment_count == 1
    assert summary.normalized_token_count == 5  # underscores are analysis boundaries
    assert summary.character_count == len(SECRET)
    assert summary.actual_audio_duration == 6.72
    assert summary.token_limit == 6 * 6.72
    assert summary.character_limit == 40 * 6.72
    assert summary.segment_metadata[0].no_speech_prob == .9
    assert summary.segment_metadata[0].avg_logprob == -2
    assert summary.duration_after_vad == 4.5
    assert not summary.output_budget_exceeded


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_privacy(enabled, caplog, tmp_path):
    checked = rejected()
    output = []
    assert display_result(checked, output.append, safety_diagnostics=enabled) == 1
    assert output[:2] == ["STT error: unusable_audio", "Safety reasons: no_speech"]
    assert len(output) == (3 if enabled else 2)
    if enabled:
        assert json.loads(output[-1]) == checked.safety_summary.model_dump(mode="json")
    for value in (str(output), caplog.text, repr(checked), str(checked),
                  repr(checked._diagnostics), checked.model_dump_json(),
                  str(checked.model_dump()), repr(checked.safety_summary)):
        assert SECRET not in value
    assert list(tmp_path.iterdir()) == []


def test_summary_schema_forbids_text():
    values = rejected().safety_summary.model_dump()
    with pytest.raises(ValidationError):
        SafetySummary(**values, transcript=SECRET)
    assert set(values) == {
        "rejection_reasons", "actual_audio_duration", "original_segment_count",
        "normalized_token_count", "character_count", "token_limit", "character_limit",
        "segment_metadata", "duration_after_vad", "output_budget_exceeded",
    }


def test_cancel_discards_all_diagnostics():
    cancel = Event()
    cancel.set()
    checked = apply_output_safety(rejected(), Settings(), cancel)
    assert checked.status == "cancelled"
    assert checked.safety_summary is None and checked._diagnostics is None
    assert checked.rejection_reasons == ()


def test_service_second_gate_keeps_evidence():
    class Engine:
        def transcribe(self, request, cancel=None):
            return rejected()
    checked = TranscriptionService(Settings(), Engine()).transcribe_audio(audio(6.72))
    assert checked.rejection_reasons == ("no_speech",)
    assert checked.safety_summary.original_segment_count == 1
    assert checked.safety_summary.normalized_token_count == 5
    assert checked.safety_summary.duration_after_vad == 4.5


def test_one_shot_generator_consumed_before_empty_check():
    consumed = []
    class Model:
        supported_languages = ["en"]
        def transcribe(self, *args, **kwargs):
            def generate():
                consumed.append(1)
                item = segment(SECRET)
                item.no_speech_prob, item.avg_logprob = .9, -2
                yield item
            return generate(), SimpleNamespace(language="en", language_probability=.9,
                                                duration_after_vad=3.25)
    engine = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: Model())
    checked = TranscriptionService(Settings(), engine).transcribe_audio(audio(6))
    assert consumed == [1]
    assert checked.rejection_reasons == ("no_speech",)
    assert checked.safety_summary.duration_after_vad == 3.25
    assert checked.safety_summary.original_segment_count == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 2, "invalid"])
def test_invalid_segment_metadata_stays_failed(bad):
    item = segment(SECRET)
    item.no_speech_prob = bad
    model = FakeModel([item])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    assert checked.status == "failed" and checked.error_code == "transcription_failed"
    assert checked.safety_summary is None and checked._diagnostics is None
    assert SECRET not in checked.model_dump_json()


def test_missing_metadata_and_safe_success_unchanged():
    model = FakeModel([segment("hello")])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    assert checked.status == "succeeded" and checked.safety_summary is None
    plain, diagnostic = [], []
    display_result(checked, plain.append)
    display_result(checked, diagnostic.append, safety_diagnostics=True)
    assert plain == diagnostic


def test_mixed_segment_no_speech_policy_unchanged():
    speech, noise = segment("hello", 0, 1), segment(SECRET, 1, 2)
    speech.no_speech_prob, speech.avg_logprob = .1, -.2
    noise.no_speech_prob, noise.avg_logprob = .8, -1
    model = FakeModel([speech, noise])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio(6)))
    assert checked.rejection_reasons == ("no_speech",)
    assert checked.safety_summary.original_segment_count == 2
    assert len(checked.safety_summary.segment_metadata) == 2


@pytest.mark.parametrize("text", [
    "VoicePilot, open Spotify and play Taare Zameen Par.",
    "VoicePilot, open Spotify and play Tarja Zameenpur.",
])
@pytest.mark.parametrize("seconds", [6, 7])
def test_reported_commands_pass_text_checks(text, seconds):
    checked = apply_output_safety(result(text, seconds), Settings())
    assert checked.status == "succeeded" and checked.raw_transcript == text


@pytest.mark.parametrize("session", [False, True])
def test_cli_option_and_actual_capture_duration(session):
    class Recorder(FakeRecorder):
        def record(self, seconds, control=None):
            return super().record(seconds, control).model_copy(update={"audio": audio(6)})
    class Engine:
        def transcribe(self, request, cancel=None):
            return result(SECRET, request.audio.duration, no_speech_prob=.9, avg_logprob=-2)
    output = []
    args = ["microphone", "--language", "en", "--safety-diagnostics"]
    args += ["--session"] if session else ["--seconds", "10"]
    assert main(args, settings=Settings(stt_local_files_only=True), engine=Engine(),
                recorder=Recorder(), read=lambda _: "", write=output.append) == 1
    summary = json.loads(output[-1])
    assert summary["actual_audio_duration"] == 6
    assert summary["token_limit"] == 36 and summary["character_limit"] == 240
    assert SECRET not in str(output)


def test_budget_cutoff_summary_is_bounded():
    settings = Settings(stt_safety_max_segments=1)
    model = FakeModel([segment("hello"), segment(SECRET)])
    checked = FasterWhisperEngine(settings, model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    summary = checked.safety_summary
    assert summary.original_segment_count == 2
    assert summary.output_budget_exceeded
    assert summary.normalized_token_count is None
    assert summary.character_count == len("hello") + len(SECRET)
    assert SECRET not in summary.model_dump_json()


def test_empty_output_summary():
    model = FakeModel([])
    checked = FasterWhisperEngine(Settings(), model_factory=lambda *a, **kw: model).transcribe(
        TranscriptionRequest(audio=audio()))
    assert checked.rejection_reasons == ("empty_output",)
    assert checked.safety_summary.original_segment_count == 0
    assert checked.safety_summary.normalized_token_count == 0


def test_gate_exception_keeps_safe_summary(monkeypatch):
    from app.stt import output_safety
    def broken(*args):
        raise ValueError(SECRET)
    monkeypatch.setattr(output_safety, "rejection_reasons", broken)
    checked = rejected()
    assert checked.rejection_reasons == ("safety_gate_error",)
    assert checked.safety_summary.original_segment_count == 1
    assert SECRET not in checked.model_dump_json()


def test_service_summary_uses_actual_pcm_even_for_pre_rejected_engine():
    class Engine:
        def transcribe(self, request, cancel=None):
            return rejected()
    checked = TranscriptionService(Settings(), Engine()).transcribe_audio(audio(6))
    assert checked.safety_summary.actual_audio_duration == 6
    assert checked.safety_summary.token_limit == 36
    assert checked.rejection_reasons == ("no_speech",)


def test_character_and_token_counts_include_segment_boundaries():
    from app.stt.models import TranscriptSegment
    source = result("a b").model_copy(update={
        "segments": (TranscriptSegment(text="a", start=0, end=1, no_speech_prob=.9, avg_logprob=-2),
                     TranscriptSegment(text="b", start=1, end=2)),
    })
    summary = apply_output_safety(source, Settings()).safety_summary
    assert summary.character_count == 3 and summary.normalized_token_count == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, "private"])
def test_invalid_optional_vad_duration_is_unavailable(value):
    checked = apply_output_safety(result(SECRET, no_speech_prob=.9, avg_logprob=-2),
                                  Settings(), duration_after_vad=value)
    assert checked.rejection_reasons == ("no_speech",)
    assert checked.safety_summary.duration_after_vad is None


def test_metadata_summary_has_finite_size():
    from app.stt.output_safety import OutputBudget
    budget = OutputBudget(Settings(stt_safety_max_segments=4096))
    for _ in range(4097):
        if not budget.add(""):
            break
    summary = budget.summary(("output_budget_exceeded",), 6)
    assert summary.original_segment_count == 4097
    assert len(summary.segment_metadata) == 4096
    assert summary.output_budget_exceeded


def test_engine_cancelled_result_discards_existing_summary():
    checked = rejected().model_copy(update={"status": "cancelled"})
    checked = apply_output_safety(checked, Settings())
    assert checked.safety_summary is None and checked._diagnostics is None
    assert checked.rejection_reasons == ()


def test_rejection_retains_no_private_text_even_in_pickle():
    import pickle
    checked = rejected()
    assert checked._diagnostics is None
    assert SECRET.encode() not in pickle.dumps(checked)


def test_extreme_optional_metadata_is_unavailable():
    checked = apply_output_safety(result(SECRET, no_speech_prob=.9, avg_logprob=-2),
                                  Settings(), duration_after_vad=10 ** 1000)
    assert checked.rejection_reasons == ("no_speech",)
    assert checked.safety_summary.duration_after_vad is None
