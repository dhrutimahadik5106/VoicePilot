import pytest
from pydantic import ValidationError

from app.commands.models import DatasetRow, Resolution, ResolverConfig


def row(**changes):
    values = dict(schema_version="1.0", command_id="vp3b-test-001", language="en",
                  input_transcript="open Spotify", canonical_intent="open_application",
                  entities={"application": "Spotify"}, canonical_command="Open Spotify",
                  variation_type="canonical", expected_confirmation_requirement=False,
                  source_type="synthetic_text")
    return values | changes


@pytest.mark.parametrize("changes", [
    {"schema_version": "2.0"}, {"command_id": "personal@email.example"},
    {"language": "xx"}, {"input_transcript": " "},
    {"entities": {"file": "private"}}, {"canonical_command": "Delete files"},
    {"entities": {}}, {"source_type": "fabricated_recording"},
    {"anonymous_speaker_id": "spk_0123456789abcdef"},
    {"noise_condition": "quiet"}, {"consent_reference": "consent_12345678"},
    {"canonical_intent": None}, {"variation_type": "observed_asr_error"},
])
def test_schema_rejects_invalid_rows(changes):
    with pytest.raises(ValidationError):
        DatasetRow(**row(**changes))


def test_consented_schema_requires_reference_and_pseudonym():
    with pytest.raises(ValidationError):
        DatasetRow(**row(source_type="consented_recording"))
    valid = DatasetRow(**row(source_type="consented_recording",
        anonymous_speaker_id="spk_0123456789abcdef", consent_reference="consent_12345678",
        noise_condition="unknown"))
    assert valid.noise_condition == "unknown"


def test_unknown_schema_and_execution_prohibition():
    item = DatasetRow(**row(canonical_intent=None, entities={}, canonical_command=None,
                           variation_type="unknown", expected_confirmation_requirement=True))
    assert item.canonical_intent is None
    with pytest.raises(ValidationError):
        Resolution(raw_transcript="help", normalized_transcript="help", language="en",
                   status="resolved", requires_confirmation=False, reasons=(),
                   canonical_command="Show help", execution_permitted=True)


@pytest.mark.parametrize("changes", [
    {"acceptance_threshold": .1}, {"acceptance_threshold": float("nan")},
    {"ambiguity_margin": -1}, {"max_candidates": 1},
])
def test_config_limits(changes):
    with pytest.raises(ValidationError):
        ResolverConfig(**changes)

def test_dataset_play_application_context_validation():
    valid = row(canonical_intent="play_media",
                entities={"application": "Spotify", "media": "Taare Zameen Par"},
                canonical_command="Play Taare Zameen Par on Spotify")
    assert DatasetRow(**valid).entities["application"] == "Spotify"
    with pytest.raises(ValidationError):
        DatasetRow(**(valid | {"canonical_command": "Play Taare Zameen Par"}))
