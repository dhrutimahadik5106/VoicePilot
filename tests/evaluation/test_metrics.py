from types import SimpleNamespace

import pytest

from app.commands.resolver import CommandResolver
from app.core.config import Settings
from app.evaluation.metrics import Aggregate, distance, fraction, normalized, text_counts
from app.stt.output_safety import apply_output_safety
from tests.evaluation import row, result, isolated_stt


@pytest.mark.parametrize('reference,hypothesis,expected', [('', '', 0), ('a', '', 1), ('', 'abc', 3),
    ('kitten', 'sitting', 3), ('abc', 'ax', 2)])
def test_hand_calculated_edit_distance(reference, hypothesis, expected):
    assert distance(reference, hypothesis) == expected


def test_word_character_and_boundary_metrics():
    counts = text_counts('a b c', 'a x')
    assert counts['wer'] == (2, 3) and counts['cer'] == (2, 3)
    boundary = text_counts('ab cd', 'a bcd')
    assert boundary['boundary_error'] == (2, 3)
    assert boundary['whitespace_sensitive_cer'] == (2, 5)
    assert 'boundary_error' not in text_counts('ab cd', 'ab x')


def test_unicode_case_punctuation_and_nukta_policy():
    assert normalized('Hello,   WORLD!') == 'hello world'
    assert normalized('\u0958') == normalized('\u0915\u093c')
    assert text_counts('\u0915\u093c', '\u0915')['cer'] == (1, 2)
    assert text_counts('\u0915\u093f', '\u0915\u0940')['cer'] == (1, 2)
    original = 'Hello,  WORLD!'
    text_counts(original, 'hello world')
    assert original == 'Hello,  WORLD!'


def test_empty_references_and_rates_above_one():
    assert text_counts('', 'a b')['wer'] == (2, 0)
    assert fraction(2, 0)['percentage'] is None
    assert fraction(3, 1)['percentage'] == 300


def test_rejections_count_as_deletions_with_accepted_coverage():
    aggregate = Aggregate()
    rejected = apply_output_safety(result('stop ' * 8), Settings())
    aggregate.observe(row(), rejected)
    report = aggregate.report()
    assert report['metrics']['delivered_wer']['numerator'] == 2
    assert report['metrics']['delivered_wer']['denominator'] == 2
    assert report['metrics']['accepted_wer']['sample_count'] == 0
    assert report['metrics']['accepted_wer']['percentage'] is None
    assert report['metrics']['successful_stt_coverage']['percentage'] == 0
    assert report['metrics']['false_rejection']['percentage'] == 100


def test_non_speech_rejection_spurious_output_and_failure_separate():
    annotation = row(ground_truth='', content='non_speech', usable_speech=False, task='dictation',
                     expected_intent=None, expected_entities={}, expected_canonical=None, expected_confirmation=True)
    aggregate = Aggregate()
    rejected = apply_output_safety(result('stop ' * 8), Settings())
    aggregate.observe(annotation, rejected)
    aggregate.observe(annotation, result('invented fictional words'))
    report = aggregate.report()['metrics']
    assert report['non_speech_rejection']['percentage'] == 50
    assert report['successful_spurious_output']['percentage'] == 50
    assert report['empty_reference_word_insertions']['numerator'] == 3


def test_command_accuracy_false_accept_denominators_and_slots():
    resolver = CommandResolver.from_directory()
    aggregate = Aggregate()
    annotation = row(expected_entities={'application': 'Chrome'}, expected_canonical='Open Chrome')
    hypothesis = result()
    aggregate.observe(annotation, hypothesis, proposal=resolver.resolve_stt(hypothesis))
    report = aggregate.report()['metrics']
    assert report['intent_accuracy']['percentage'] == 100
    assert report['exact_entity_accuracy']['percentage'] == 0
    assert report['slot_application_accuracy']['denominator'] == 1
    assert report['canonical_command_accuracy']['percentage'] == 0
    assert report['unsafe_false_accept_rate']['percentage'] == 100
    assert report['false_accept_among_accepted']['percentage'] == 100
    assert report['acceptance_coverage']['percentage'] == 100
    assert report['confirmation_rate']['percentage'] == 0


def test_runtime_counts_and_cold_status():
    aggregate = Aggregate(); aggregate.observe(row(), result())
    report = aggregate.report()
    assert report['processing_seconds']['mean'] == .4 and report['inference_seconds']['mean'] == .3
    assert report['rtf']['mean'] == .4 and report['cold_count'] == 1 and report['warm_count'] == 0
