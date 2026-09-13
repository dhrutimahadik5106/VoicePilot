import io
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.audio.wav import write_pcm_wav
from app.core.config import Settings
from app.stt.context import Vocabulary, PUBLIC_CONTEXT, build_hints, load_vocabulary, load_overlay
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.parity import ComparisonEngine, compare_capture, settings_snapshot
from app.stt.service import TranscriptionService, read_pcm_wav_stream
from tests.evaluation import Model, Tokenizer, SECRET
from tests.stt import audio, isolated_stt


def test_public_schema_and_categories():
    vocabulary = load_vocabulary()
    assert json.loads(PUBLIC_CONTEXT.with_name('context-schema-v1.json').read_text()) == Vocabulary.model_json_schema()
    assert {e.category for e in vocabulary.entries} == {'assistant', 'application', 'action', 'location', 'media'}
    assert len([e for e in vocabulary.entries if e.category == 'application']) == 5
    assert all(f.review_status == 'reviewed' for e in vocabulary.entries for f in e.forms)


@pytest.mark.parametrize('language', ['en', 'hi', 'mr', 'mixed', 'auto', None])
def test_language_provenance_and_deterministic_budgets(language):
    vocabulary = load_vocabulary()
    hints = build_hints(vocabulary, language, tokenizer=Tokenizer())
    assert hints.status == 'ready' and hints.selected_count > 0
    assert hints == build_hints(vocabulary, language, tokenizer=Tokenizer())
    assert len(hints.hotwords) <= 300 and len(hints.initial_prompt) <= 500 and hints.token_count <= 96
    if language in {'en', 'hi', 'mr'}:
        assert all(lang in {language, 'mixed'} for lang, _, _ in hints.provenance)
    assert len(hints.hotwords.split(', ')) == len(set(hints.hotwords.casefold().split(', ')))


@pytest.mark.parametrize('limit', [0, 1, 8, 30, 96])
def test_token_budget_never_exceeded(limit):
    hints = build_hints(load_vocabulary(), tokenizer=Tokenizer(), token_limit=limit)
    assert hints.token_count <= limit


@pytest.mark.parametrize('limit', [0, 1, 10, 40])
def test_character_budget_never_exceeded(limit):
    hints = build_hints(load_vocabulary(), tokenizer=Tokenizer(), hotword_limit=limit, prompt_limit=0)
    assert len(hints.hotwords) <= limit and hints.initial_prompt == ''


def test_tokenizer_unavailable_error_and_invalid_result_are_safe():
    assert build_hints(load_vocabulary()).status == 'tokenizer_unavailable'
    class Broken:
        def encode(self, *a, **kw): raise ValueError(SECRET)
    hints = build_hints(load_vocabulary(), tokenizer=Broken())
    assert hints.status == 'tokenizer_error' and hints.hotwords == ''
    assert SECRET not in repr(hints) + hints.model_dump_json()
    class Invalid:
        def encode(self, *a, **kw): return 'not token IDs'
    assert build_hints(load_vocabulary(), tokenizer=Invalid()).status == 'tokenizer_error'


def test_private_overlay_explicit_and_never_serialized(tmp_path):
    values = json.loads(PUBLIC_CONTEXT.read_text(encoding='utf-8'))
    values['entries'] = [values['entries'][0]]
    values['entries'][0]['forms'] = [values['entries'][0]['forms'][0]]
    values['entries'][0]['forms'][0]['text'] = SECRET
    path = tmp_path / 'vocabulary.private.json'
    path.write_text(json.dumps(values), encoding='utf-8')
    overlay = load_overlay(path.name, tmp_path)
    # A public-only call cannot discover files in cwd.
    public = build_hints(load_vocabulary(), 'en', tokenizer=Tokenizer())
    assert SECRET not in public.hotwords
    private = build_hints(overlay, 'en', tokenizer=Tokenizer())
    assert SECRET in private.hotwords
    assert SECRET not in repr(overlay) + overlay.model_dump_json() + repr(private) + private.model_dump_json()


def test_observed_errors_excluded_and_require_confirmation():
    values = json.loads(PUBLIC_CONTEXT.read_text(encoding='utf-8'))
    form = values['entries'][0]['forms'][0]
    form.update(text=SECRET, kind='observed_asr_error', hint_eligible=False, requires_confirmation=True)
    vocabulary = Vocabulary.model_validate(values)
    assert SECRET not in build_hints(vocabulary, tokenizer=Tokenizer()).hotwords
    form['hint_eligible'] = True
    with pytest.raises(ValidationError): Vocabulary.model_validate(values)


def test_effective_hints_identical_direct_file_session_and_parity(tmp_path):
    settings = Settings(stt_contextual_enabled=True, stt_language='hi')
    model = Model()
    engine = FasterWhisperEngine(settings, model_factory=lambda *a, **kw: model)
    service = TranscriptionService(settings, engine)
    source = audio()
    # Direct and a second session call reuse the same engine/model.
    service.transcribe_audio(source)
    service.transcribe_audio(source)
    path = tmp_path / 'fictional.wav'
    with path.open('wb') as handle: write_pcm_wav(source, handle)
    service.transcribe_file(path)
    parity_model = Model()
    parity = ComparisonEngine(settings_snapshot(settings), model_factory=lambda *a, **kw: parity_model)
    compare_capture(source, parity)
    options = [kwargs for _, kwargs in model.calls + parity_model.calls]
    assert len(options) == 5 and all(item == options[0] for item in options)
    assert options[0]['hotwords'] and options[0]['initial_prompt'] is None


def test_production_hints_unchanged_when_context_disabled():
    model = Model()
    settings = Settings()
    TranscriptionService(settings, FasterWhisperEngine(settings, model_factory=lambda *a, **kw: model)).transcribe_audio(audio())
    assert model.calls[0][1]['initial_prompt'] == settings.stt_initial_prompt
    assert model.calls[0][1]['hotwords'] == settings.stt_hotwords
    assert settings.stt_contextual_enabled is False


@pytest.mark.parametrize('mode', ['microphone', 'file', 'session', 'parity'])
def test_contextual_cli_flags_reach_actual_engine(mode, tmp_path, monkeypatch):
    from app.stt import cli, parity
    from tests.stt.test_cli import FakeRecorder
    model = Model()
    seen = []
    def factory(settings):
        seen.append(settings.stt_contextual_enabled)
        cls = ComparisonEngine if mode == 'parity' else FasterWhisperEngine
        return cls(settings, model_factory=lambda *a, **kw: model)
    settings = Settings(stt_local_files_only=True)
    flags = ['--contextual', '--language', 'hi']
    if mode == 'parity':
        assert parity.main(flags, settings=settings, recorder=FakeRecorder(), engine_factory=factory,
                           read=lambda _: '', write=lambda _: None) == 0
    else:
        monkeypatch.setattr(cli, 'FasterWhisperEngine', factory)
        if mode == 'file':
            path = tmp_path / 'fictional.wav'
            with path.open('wb') as handle: write_pcm_wav(audio(), handle)
            args = ['file', str(path), *flags]
        else:
            args = ['microphone', *flags] + (['--session'] if mode == 'session' else ['--seconds', '1'])
        answers = iter(['', '', 'q'])
        assert cli.main(args, settings=settings, recorder=FakeRecorder(), read=lambda _: next(answers), write=lambda _: None) == 0
    expected = build_hints(load_vocabulary(), 'hi', tokenizer=Tokenizer()).hotwords
    assert seen == [True] and model.calls
    assert all(kw['hotwords'] == expected and kw['initial_prompt'] is None for _, kw in model.calls)
