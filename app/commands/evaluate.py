"""Local seed evaluation; this is not a research/generalization benchmark."""
from collections import Counter


def metric(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "percentage": 100 * numerator / denominator if denominator else None}


def evaluate(rows, resolver):
    counts = dict(intent=0, entities=0, canonical=0, confirmation=0, accepted=0,
                  false_accept=0, unsafe_opportunities=0)
    for row in rows:
        result = resolver.resolve(row.input_transcript, language=row.language)
        intent_ok = result.intent == row.canonical_intent
        entity_ok = result.entities == row.entities
        canonical_ok = result.canonical_command == row.canonical_command
        correct = intent_ok and entity_ok and canonical_ok
        accepted = result.status == "resolved" and not result.requires_confirmation
        unsafe = row.expected_confirmation_requirement or row.canonical_intent is None or not correct
        counts["intent"] += intent_ok
        counts["entities"] += entity_ok
        counts["canonical"] += canonical_ok
        counts["confirmation"] += result.requires_confirmation
        counts["accepted"] += accepted
        counts["unsafe_opportunities"] += unsafe
        counts["false_accept"] += accepted and unsafe
    total = len(rows)
    return {
        "dataset_role": "development/test text evaluation; not held-out research evidence",
        "source_counts": dict(Counter(row.source_type for row in rows)),
        "language_counts": dict(Counter(row.language for row in rows)),
        "variation_counts": dict(Counter(row.variation_type for row in rows)),
        "rows": total,
        "intent_accuracy": metric(counts["intent"], total),
        "exact_entity_accuracy": metric(counts["entities"], total),
        "canonical_command_accuracy": metric(counts["canonical"], total),
        "confirmation_rate": metric(counts["confirmation"], total),
        "acceptance_coverage": metric(counts["accepted"], total),
        "false_accept_rate": metric(counts["false_accept"], counts["unsafe_opportunities"]),
        "false_accept_among_accepted": metric(counts["false_accept"], counts["accepted"]),
        "false_accept_definition": "Accepted without confirmation despite incorrect interpretation, unknown intent, or expected confirmation.",
        "false_accept_denominator": "Rows requiring confirmation, labeled unknown, or interpreted incorrectly (union).",
        "zero_denominator": "percentage is null when denominator is zero",
    }
