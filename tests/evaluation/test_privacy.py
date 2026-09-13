import json
from pathlib import Path
import subprocess

import pytest

from app.core.config import Settings
from app.evaluation.cli import main
from app.evaluation.dataset import EvaluationError, load_manifest
from app.evaluation.stt import run_evaluation
from app.stt.refinement import refine
from tests.evaluation import SECRET, row, row_data, result, manifest, factory_collector, audio, isolated_stt


def test_annotation_repr_and_serialization_exclude_all_private_text():
    item = row(ground_truth=SECRET, expected_entities={'application': SECRET}, expected_canonical="Open " + SECRET)
    assert SECRET not in repr(item) + item.model_dump_json() + repr(manifest(item)) + manifest(item).model_dump_json()
    assert SECRET not in refine(result(SECRET)).model_dump_json()


@pytest.mark.parametrize('reject', [False, True])
@pytest.mark.parametrize('show', [False, True])
def test_default_aggregates_hide_text_and_rejected_hypotheses_never_return(reject, show, caplog):
    models, engines = [], []
    item = row(ground_truth='fictional reference words', task='dictation', expected_intent=None,
               expected_entities={}, expected_canonical=None)
    report = run_evaluation(manifest(item), Settings(), audio_loader=lambda _: audio(), include_utterances=show,
                           engine_factory=factory_collector(models, engines, text=SECRET, reject=reject))
    assert (SECRET in json.dumps(report)) is (show and not reject)
    assert SECRET not in caplog.text
    assert all(SECRET not in repr(e) for e in engines)
    if reject:
        assert report['arms']['B']['overall']['metrics']['accepted_wer']['sample_count'] == 0


def test_ground_truth_private_by_default(caplog):
    models, engines = [], []
    report = run_evaluation(manifest(row(ground_truth=SECRET)), Settings(), audio_loader=lambda _: audio(),
                           engine_factory=factory_collector(models, engines))
    assert SECRET not in json.dumps(report) + caplog.text


def test_invalid_manifest_errors_never_echo_text(tmp_path):
    path = tmp_path / 'fixture.private.json'
    values = row_data(ground_truth=SECRET, review_status=SECRET)
    path.write_text(json.dumps({'schema_version': '1.0', 'rows': [values]}))
    with pytest.raises(EvaluationError) as caught: load_manifest(path, root=tmp_path)
    assert SECRET not in repr(caught.value) + str(caught.value)
    output=[]
    assert main(['validate-manifest', '--private-root', str(tmp_path), '--manifest', path.name], write=output.append) == 1
    assert SECRET not in str(output)


def test_ignore_boundaries_cover_private_artifacts():
    root=Path(__file__).resolve().parents[2]
    paths=['data/stt/private/manifest.json', 'data/stt/private/vocabulary.json', 'data/stt/private/audio/a.wav',
           'example.private.jsonl', 'example.utterances.jsonl', 'evaluation-exports/report.json']
    completed=subprocess.run(['git','check-ignore','--no-index',*paths], cwd=root, capture_output=True, text=True)
    assert completed.returncode == 0 and len(completed.stdout.splitlines()) == len(paths)


def test_imports_create_no_directories_or_model_access(tmp_path):
    import importlib
    for name in ('app.evaluation.models','app.evaluation.dataset','app.evaluation.metrics','app.evaluation.stt',
                 'app.evaluation.cli','app.stt.context','app.stt.refinement'):
        assert importlib.import_module(name)
    assert list(tmp_path.iterdir()) == []


def test_argument_errors_do_not_echo_private_values(capsys):
    output=[]
    assert main(['inspect-context', '--language', SECRET], write=output.append) == 1
    assert SECRET not in str(output) + capsys.readouterr().err


def test_private_backend_exception_never_leaks(caplog):
    def broken(_): raise ValueError(SECRET)
    with pytest.raises(EvaluationError) as caught:
        run_evaluation(manifest(), Settings(), audio_loader=broken)
    assert SECRET not in str(caught.value) + caplog.text
