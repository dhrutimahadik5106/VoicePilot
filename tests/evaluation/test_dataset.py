import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import EvaluationError, load_manifest, private_path, validate_manifest, evidence_label
from app.evaluation.models import Manifest, EvaluationRow
from app.stt.context import PUBLIC_CONTEXT, Vocabulary
from tests.evaluation import row, row_data, manifest, isolated_stt, SECRET


def test_reviewed_synthetic_manifest_and_personal_evidence_label():
    data = validate_manifest(manifest())
    assert evidence_label(data.rows) == 'personal_development_only'
    assert len(data.rows) == 1


@pytest.mark.parametrize('field', ['speaker', 'session', 'recording_group'])
def test_cross_split_leakage(field):
    first = row()
    values = dict(recording_id='rec_00000002', speaker='spk_0000000000000002', session='session_00000002',
                  recording_group='group_00000002', split='test')
    values[field] = getattr(first, field)
    with pytest.raises(EvaluationError, match='invalid_manifest_or_leakage'):
        validate_manifest(manifest(first, row(**values)))


def test_disjoint_splits_and_duplicate_recording_ids():
    second = row(recording_id='rec_00000002', speaker='spk_0000000000000002', session='session_00000002',
                 recording_group='group_00000002', split='test')
    assert validate_manifest(manifest(row(), second))
    with pytest.raises(EvaluationError): validate_manifest(manifest(row(), row()))


@pytest.mark.parametrize('field,value', [('review_status', 'pending'), ('language', 'unknown'),
                                       ('consent_reference', None), ('evaluation_permitted', False),
                                       ('retention_review_date', None), ('audio_sha256', None)])
def test_real_annotation_requires_review_and_consent(field, value):
    data = row_data(source_type='consented_recording', audio='fictional.wav', audio_sha256='a'*64,
                    consent_reference='consent_fictional000', evaluation_permitted=True, retention_review_date='2099-01-01')
    data[field] = value
    with pytest.raises(ValidationError): EvaluationRow.model_validate(data)


def test_unknown_version_rejected():
    with pytest.raises(ValidationError): Manifest.model_validate({'schema_version': '2.0', 'rows': [row_data()]})


def test_paths_must_stay_in_explicit_root(tmp_path):
    root = tmp_path / 'approved'; root.mkdir()
    inside = root / 'manifest.private.json'; inside.write_text('{}')
    outside = tmp_path / 'outside.private.json'; outside.write_text('{}')
    assert private_path(root, inside.name) == inside.resolve()
    for path in (outside, '../outside.private.json', 'missing.private.json'):
        with pytest.raises(EvaluationError, match='invalid_private_path'): private_path(root, path)


def test_public_repository_cannot_be_private_root():
    with pytest.raises(EvaluationError): private_path(PUBLIC_CONTEXT.parent, PUBLIC_CONTEXT)


def test_private_manifest_loading_and_no_audio_reads(tmp_path):
    path = tmp_path / 'manifest.private.json'
    path.write_text(json.dumps({'schema_version': '1.0', 'rows': [row_data()]}))
    assert len(load_manifest(path.name, root=tmp_path).rows) == 1
    path.write_text(SECRET)
    with pytest.raises(EvaluationError) as caught: load_manifest(path.name, root=tmp_path)
    assert SECRET not in str(caught.value)


def test_sentence_leakage_into_public_hints_detected():
    values = json.loads(PUBLIC_CONTEXT.read_text(encoding='utf-8'))
    values['entries'][0]['forms'][0]['text'] = 'Open Spotify!'
    with pytest.raises(EvaluationError):
        validate_manifest(manifest(), public_vocabulary=Vocabulary.model_validate(values))


def test_repeated_audio_hash_and_canonical_path_overlap(tmp_path):
    (tmp_path / 'fake.wav').write_bytes(b'fictional container placeholder; not read during validation')
    def real(index, **changes):
        values = dict(recording_id=f'rec_0000000{index}', source_type='consented_recording', audio='fake.wav',
                      audio_sha256=str(index)*64, consent_reference='consent_fictional000', evaluation_permitted=True,
                      retention_review_date='2099-01-01', speaker=f'spk_{index:016x}', session=f'session_0000000{index}',
                      recording_group=f'group_0000000{index}', split='development' if index == 1 else 'test')
        values.update(changes)
        return row(**values)
    with pytest.raises(EvaluationError): validate_manifest(manifest(real(1), real(2, audio='./fake.wav')), root=tmp_path)
    (tmp_path / 'second.wav').write_bytes(b'fictional')
    with pytest.raises(EvaluationError):
        validate_manifest(manifest(real(1), real(2, audio='second.wav', audio_sha256='1'*64)), root=tmp_path)


def test_expired_consent_review_and_missing_root(tmp_path):
    (tmp_path / 'fake.wav').write_bytes(b'fictional')
    item = row(source_type='consented_recording', audio='fake.wav', audio_sha256='a'*64,
               consent_reference='consent_fictional000', evaluation_permitted=True, retention_review_date='2000-01-01')
    with pytest.raises(EvaluationError): validate_manifest(manifest(item), root=tmp_path)
    with pytest.raises(EvaluationError): validate_manifest(manifest(item))


@pytest.mark.parametrize('changes', [
    {'expected_canonical': 'Wrong proposal'},
    {'expected_entities': {'unexpected_slot': 'fictional'}},
    {'expected_intent': None, 'expected_entities': {}, 'expected_canonical': None, 'expected_confirmation': False},
    {'expected_entities': {}, 'expected_canonical': None, 'expected_confirmation': False},
])
def test_inconsistent_command_annotations_rejected(changes):
    with pytest.raises(ValidationError): row(**changes)
