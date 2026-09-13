"""Fictional fixtures; all files, when required, live under pytest tmp_path."""
from types import SimpleNamespace
from uuid import uuid4

from app.evaluation.models import EvaluationRow, Manifest
from app.stt.models import TranscriptSegment, TranscriptionResult
from app.stt.parity import ComparisonEngine
from tests.stt import audio, isolated_stt, segment

SECRET = "FICTIONAL_PRIVATE_SENTINEL_3E"


def row_data(**changes):
    value = dict(recording_id="rec_00000001", source_type="synthetic_text", ground_truth="open Spotify",
                 review_status="reviewed", language="en", script="Latin", speaker="spk_0000000000000001",
                 session="session_00000001", recording_group="group_00000001", split="development",
                 noise_condition="unknown", content="speech", usable_speech=True, task="command",
                 expected_intent="open_application", expected_entities={"application": "Spotify"},
                 expected_canonical="Open Spotify", expected_confirmation=False)
    value.update(changes)
    return value


def row(**changes):
    return EvaluationRow.model_validate(row_data(**changes))


def manifest(*rows):
    return Manifest(schema_version="1.0", rows=rows or (row(),))


def result(text="open Spotify", language="en", segments=None):
    segments = segments if segments is not None else (TranscriptSegment(text=text, start=0, end=.5),)
    return TranscriptionResult(audio_id=uuid4(), language=language, text=" ".join(s.text.strip() for s in segments if s.text.strip()),
        segments=segments, processing_duration=.4, inference_duration=.3, model_load_duration=.1,
        cold_start=True, source_audio_duration=1, model_name="small", device="cpu", compute_type="int8", status="succeeded")


class Tokenizer:
    def encode(self, text, **kwargs):
        return SimpleNamespace(ids=list(range(len(text))))


class Model:
    supported_languages = ["en", "hi", "mr"]
    hf_tokenizer = Tokenizer()

    def __init__(self, text="open Spotify", reject=False, empty=False, cancel=None):
        self.text, self.reject, self.empty, self.cancel = text, reject, empty, cancel
        self.calls = []

    def transcribe(self, samples, **kwargs):
        self.calls.append((samples.copy(), kwargs))
        item = segment(self.text)
        if self.reject: item.no_speech_prob, item.avg_logprob = .9, -2
        if self.cancel is not None: self.cancel.set()
        return iter([] if self.empty else [item]), SimpleNamespace(language=kwargs['language'] or 'en',
            language_probability=.9, duration_after_vad=0.0 if self.empty else len(samples) / 16000)


def factory_collector(models, engines, **options):
    def factory(settings, **kwargs):
        model = Model(**options)
        models.append(model)
        engine = ComparisonEngine(settings, model_factory=lambda *a, **kw: model, **kwargs)
        engines.append(engine)
        return engine
    return factory
