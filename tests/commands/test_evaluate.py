from types import SimpleNamespace

from app.commands.evaluate import evaluate, metric
from app.commands.models import DatasetRow
from tests.commands.test_models import row


def test_metrics_exact_numerators_and_denominators():
    rows = [
        DatasetRow(**row()),
        DatasetRow(**row(command_id="vp3b-test-002", canonical_intent=None, entities={},
                       canonical_command=None, variation_type="unknown",
                       expected_confirmation_requirement=True)),
        DatasetRow(**row(command_id="vp3b-test-003", variation_type="typo",
                       expected_confirmation_requirement=True)),
    ]
    outputs = iter([
        SimpleNamespace(intent="open_application", entities={"application": "Spotify"},
                        canonical_command="Open Spotify", status="resolved", requires_confirmation=False),
        SimpleNamespace(intent="help", entities={}, canonical_command="Show help",
                        status="resolved", requires_confirmation=False),
        SimpleNamespace(intent="open_application", entities={}, canonical_command=None,
                        status="needs_confirmation", requires_confirmation=True),
    ])
    fake = SimpleNamespace(resolve=lambda *a, **k: next(outputs))
    metrics = evaluate(rows, fake)
    assert metrics["intent_accuracy"] == metric(2, 3)
    assert metrics["exact_entity_accuracy"] == metric(2, 3)
    assert metrics["canonical_command_accuracy"] == metric(1, 3)
    assert metrics["confirmation_rate"] == metric(1, 3)
    assert metrics["acceptance_coverage"] == metric(2, 3)
    assert metrics["false_accept_rate"] == metric(1, 2)
    assert metrics["false_accept_among_accepted"] == metric(1, 2)


def test_zero_denominator_is_not_fabricated_perfect_score():
    assert metric(0, 0) == {"numerator": 0, "denominator": 0, "percentage": None}


def test_evaluation_is_deterministic(resolver):
    from app.commands.dataset import validate_dataset
    rows = validate_dataset()
    assert evaluate(rows, resolver) == evaluate(rows, resolver)
