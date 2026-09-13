import io
import hashlib
import json
from threading import Event

import numpy as np
import pytest
from pydantic import ValidationError

from app.audio.wav import write_pcm_wav
from app.core.config import Settings
from app.evaluation.cli import main, fictional_demo
from app.evaluation.dataset import EvaluationError
from app.evaluation.stt import run_evaluation, private_audio_loader
from app.stt.parity import ComparisonEngine
from tests.evaluation import row, manifest, factory_collector, Model, audio, isolated_stt, SECRET


def test_paired_arms_fixed_inputs_hints_settings_and_no_extra_decoding():
    models, engines, loaded = [], [], []
    def load(item): loaded.append(item.recording_id); return audio()
    report = run_evaluation(manifest(), Settings(), audio_loader=load, engine_factory=factory_collector(models, engines))
    assert len(loaded) == 1 and [len(m.calls) for m in models] == [1, 1]
    np.testing.assert_array_equal(models[0].calls[0][0], models[1].calls[0][0])
    assert models[0].calls[0][1]['hotwords'] is None
    assert models[1].calls[0][1]['hotwords']
    first, second = [e.settings.model_dump() for e in engines]
    assert (first | {'stt_contextual_enabled': True}) == second
    assert all(e.settings.stt_local_files_only and e._model is None and e._prepared == {} for e in engines)
    with pytest.raises(ValidationError): engines[0].settings.stt_beam_size = 7
    assert report['metadata']['prepared_inputs_equal']
    assert report['E']['implemented'] is False
    assert report['arms']['D_from_A']['overall']['metrics']['intent_accuracy']['percentage'] == 100
    assert 'utterances' not in report
    assert report['arms']['A']['en']['sample_count'] == 1


@pytest.mark.parametrize('mode,expected', [('manifest', 'hi'), ('auto', None)])
def test_language_mode_is_explicit(mode, expected):
    models, engines = [], []
    item = row(language='hi', script='Devanagari')
    run_evaluation(manifest(item), Settings(), language_mode=mode, audio_loader=lambda _: audio(),
                   engine_factory=factory_collector(models, engines))
    assert all(m.calls[0][1]['language'] == expected for m in models)


def test_shadow_reuses_success_without_becoming_resolver_input():
    models, engines = [], []
    report = run_evaluation(manifest(row(language='hi', ground_truth='\u0915\u0943\u092a\u092f\u093e', task='dictation',
                              expected_intent=None, expected_entities={}, expected_canonical=None)), Settings(),
        audio_loader=lambda _: audio(), engine_factory=factory_collector(models, engines, text='\u0915\u0943\u0020\u092a\u092f\u093e'),
        include_utterances=True)
    assert report['arms']['B']['overall']['metrics']['delivered_wer']['numerator'] > 0
    assert report['arms']['C']['overall']['metrics']['delivered_wer']['numerator'] == 0
    assert report['utterances'][0]['B'] == '\u0915\u0943\u0020\u092a\u092f\u093e'
    assert [len(m.calls) for m in models] == [1, 1]


def test_medium_placeholder_never_constructs_model():
    with pytest.raises(EvaluationError, match='only_small_approved'):
        run_evaluation(manifest(), Settings(whisper_model='medium'), audio_loader=lambda _: pytest.fail('audio accessed'))


def test_unvalidated_splits_fail_before_audio_access():
    second = row(recording_id='rec_00000002', split='test')
    with pytest.raises(EvaluationError):
        run_evaluation(manifest(row(), second), Settings(), audio_loader=lambda _: pytest.fail('audio accessed'))


def test_cancelled_evaluation_disposes_snapshots_and_returns_no_report():
    cancel = Event(); models, engines = [], []
    report = run_evaluation(manifest(), Settings(), audio_loader=lambda _: audio(), cancel=cancel,
                           engine_factory=factory_collector(models, engines, cancel=cancel), include_utterances=True)
    assert report == {'status': 'cancelled'}
    assert all(e._prepared == {} and e._model is None for e in engines)


def test_audio_loader_hash_and_memory_wav(tmp_path):
    source = audio()
    with io.BytesIO() as buffer:
        write_pcm_wav(source, buffer); data = buffer.getvalue()
    (tmp_path / 'fictional.wav').write_bytes(data)
    item = row(source_type='consented_recording', audio='fictional.wav', audio_sha256=hashlib.sha256(data).hexdigest(),
               consent_reference='consent_fictional000', evaluation_permitted=True, retention_review_date='2099-01-01')
    loaded = private_audio_loader(tmp_path, 120)(item)
    np.testing.assert_array_equal(source.samples, loaded.samples)
    with pytest.raises(EvaluationError): private_audio_loader(tmp_path, 120)(item.model_copy(update={'audio_sha256': '0'*64}))


def test_schema_and_fictional_demo_without_model_imports(tmp_path):
    output=[]
    assert main(['validate-schema'], write=output.append) == 0
    assert json.loads(output[-1])['valid']
    demo = fictional_demo()
    assert demo['evidence'] == 'fictional_fake_pipeline_demo_not_accuracy_evidence'
    assert demo['metadata']['context_status'] == 'ready'
    assert list(tmp_path.iterdir()) == []


def test_cli_does_not_run_private_audio_without_explicit_flag(tmp_path, monkeypatch):
    from app.evaluation import cli
    monkeypatch.setattr(cli, 'load_manifest', lambda *a, **kw: manifest())
    monkeypatch.setattr(cli, 'run_evaluation', lambda *a, **kw: pytest.fail('unauthorized evaluation'))
    output=[]
    assert main(['run', '--private-root', str(tmp_path), '--manifest', 'fixture.private.json'], write=output.append) == 1
    assert output == ['{"error":"invalid_evaluation_request"}']


def test_cli_run_selects_split_and_requires_explicit_utterance_display(tmp_path, monkeypatch):
    from app.evaluation import cli
    first = row()
    second = row(recording_id='rec_00000002', speaker='spk_0000000000000002', session='session_00000002',
                 recording_group='group_00000002', split='test')
    monkeypatch.setattr(cli, 'load_manifest', lambda *a, **kw: manifest(first, second))
    calls=[]
    def run(selected, settings, **kwargs):
        calls.append((selected, settings, kwargs))
        return {'status': 'fictional_spy_only'}
    monkeypatch.setattr(cli, 'run_evaluation', run)
    assert main(['run', '--private-root', str(tmp_path), '--manifest', 'fixture.private.json',
                 '--consent-evaluation', '--split', 'test', '--language', 'auto'], write=lambda _: None) == 0
    selected, settings, kwargs = calls[0]
    assert len(selected.rows) == 1 and selected.rows[0].split == 'test'
    assert kwargs['include_utterances'] is False and kwargs['language_mode'] == 'auto'
    assert kwargs['overlay'] is None and settings.stt_local_files_only


def test_order_alternates_but_each_row_uses_identical_audio():
    models, engines, order = [], [], []
    base = factory_collector(models, engines)
    def factory(settings, **kwargs):
        engine = base(settings, **kwargs)
        original = engine.transcribe
        def wrapped(*a, **kw):
            order.append('B' if settings.stt_contextual_enabled else 'A')
            return original(*a, **kw)
        engine.transcribe = wrapped
        return engine
    second = row(recording_id='rec_00000002', recording_group='group_00000002')
    report = run_evaluation(manifest(row(), second), Settings(), audio_loader=lambda _: audio(), engine_factory=factory)
    assert order == ['A', 'B', 'B', 'A']
    assert report['metadata']['context_status_counts'] == {'ready': 2}
    assert report['metadata']['split_counts'] == {'development': 2}
    assert report['arms']['A']['overall']['weighted_rtf'] >= 0
