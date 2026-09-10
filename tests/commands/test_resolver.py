import pytest

from app.commands.models import ResolverConfig
from app.commands.resolver import CommandResolver


@pytest.mark.parametrize("text,intent,entities", [
    ("Open Spotify", "open_application", {"application": "Spotify"}),
    ("please launch Google Chrome", "open_application", {"application": "Chrome"}),
    ("स्पॉटिफाई खोलो", "open_application", {"application": "Spotify"}),
    ("स्पॉटिफाय उघड", "open_application", {"application": "Spotify"}),
    ("VoicePilot Spotify ओपन करो", "open_application", {"application": "Spotify"}),
    ("तारे ज़मीन पर चलाओ", "play_media", {"media": "Taare Zameen Par"}),
    ("तारे जमीन पर लावा", "play_media", {"media": "Taare Zameen Par"}),
    ("आवाज वाढव", "volume_up", {}),
    ("pause करो", "pause", {}),
])
def test_exact_and_multilingual(resolver, text, intent, entities):
    result = resolver.resolve(text)
    assert result.intent == intent and result.entities == entities
    assert result.status == "resolved" and not result.requires_confirmation
    assert not result.execution_permitted
    assert result.score_kind == "heuristic_match_score"


def test_raw_normalized_canonical_are_distinct(resolver):
    raw = "  Hey Voice Pilot,\t OPEN   Spotify!  "
    result = resolver.resolve(raw)
    assert result.raw_transcript == raw
    assert result.normalized_transcript == "hey voice pilot open spotify"
    assert result.canonical_command == "Open Spotify"


def test_observed_error_requires_confirmation(resolver):
    result = resolver.resolve("play Tharism Infer")
    assert result.canonical_command == "Play Taare Zameen Par"
    assert result.raw_transcript == "play Tharism Infer"
    assert result.normalized_transcript == "play tharism infer"
    assert result.requires_confirmation and result.status == "needs_confirmation"
    assert result.candidates[0].match_type == "observed_asr_error"
    assert "observed_asr_error" in result.reasons


@pytest.mark.parametrize("text", ["open browser", "play taare", "open music app"])
def test_ambiguous_entities_not_selected(resolver, text):
    result = resolver.resolve(text)
    assert result.requires_confirmation and len(result.candidates) >= 2
    assert result.entities == {} and result.canonical_command is None
    assert "ambiguous_entity" in result.reasons


def test_fuzzy_suggestion_never_silently_replaces_entity(resolver):
    result = resolver.resolve("open Spotfy")
    assert result.candidates[0].canonical_name == "Spotify"
    assert result.entities == {} and result.canonical_command is None
    assert result.requires_confirmation and "low_heuristic_score" in result.reasons


@pytest.mark.parametrize("text", [
    "don't open Spotify", "do not open Spotify", "Spotify मत खोलो", "Spotify उघडू नको",
    "open Spotify and play Taare Zameen Par", "Chrome उघड आणि आवाज वाढव",
    "open Spotify; mute", "open Spotify\nmute", "open Spotify && whoami",
    "open NebulaDesk", "play Unlisted Midnight Melody", "open Spotify Lite", "open",
    "tell me the weather", "",
])
def test_negative_or_unknown_never_accepted(resolver, text):
    result = resolver.resolve(text)
    assert result.requires_confirmation
    assert result.status != "resolved"
    assert result.canonical_command is None
    assert result.raw_transcript == text


def test_config_cannot_promote_observed_or_fuzzy_to_accepted(resolver):
    configured = CommandResolver(resolver.aliases, resolver.intents,
                                 ResolverConfig(acceptance_threshold=.9))
    for text in ("play Tharism Infer", "open Spotfy"):
        assert configured.resolve(text).requires_confirmation


def test_oversize_text_rejected(resolver):
    with pytest.raises(ValueError):
        resolver.resolve("x" * 501)
