from types import SimpleNamespace


def test_stt_raw_property_is_used_exactly(resolver):
    original = " Hey Voice Pilot,  open Spotify! "
    fake_stt = SimpleNamespace(status="succeeded", language="en",
                               raw_transcript=original, normalized_transcript="DO NOT USE THIS")
    result = resolver.resolve_stt(fake_stt)
    assert result.raw_transcript == original
    assert result.canonical_command == "Open Spotify"
    assert fake_stt.normalized_transcript == "DO NOT USE THIS"


def test_failed_stt_is_never_interpreted(resolver):
    fake_stt = SimpleNamespace(status="failed", raw_transcript="open Spotify")
    result = resolver.resolve_stt(fake_stt)
    assert result.status == "unknown" and result.intent is None
    assert result.requires_confirmation and not result.execution_permitted
