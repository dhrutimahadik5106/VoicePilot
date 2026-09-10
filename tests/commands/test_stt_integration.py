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


def test_rejected_stt_never_exposes_diagnostics(resolver):
    from app.core.config import Settings
    from app.stt.output_safety import apply_output_safety
    from tests.stt.test_output_safety import result
    rejected = apply_output_safety(result("Google " * 8), Settings())
    proposal = resolver.resolve_stt(rejected)
    assert proposal.raw_transcript == proposal.normalized_transcript == ""
    assert proposal.intent is None and not proposal.execution_permitted
    assert "Google" not in proposal.model_dump_json()


def test_all_non_success_statuses_blocked_without_reading_text(resolver):
    class NonSuccess:
        @property
        def raw_transcript(self):
            raise AssertionError("Do not read rejected transcript")
    for status in ("failed", "cancelled", "unusable_audio"):
        source = NonSuccess()
        source.status = status
        proposal = resolver.resolve_stt(source)
        assert proposal.intent is None and not proposal.execution_permitted
        assert proposal.raw_transcript == ""


def test_safe_stt_workflow_retains_entities(resolver):
    from app.core.config import Settings
    from app.stt.output_safety import apply_output_safety
    from tests.stt.test_output_safety import result
    text = "Hey Voice Pilot, open Spotify and play Taare Zameen Par."
    proposal = resolver.resolve_stt(apply_output_safety(result(text), Settings()))
    assert proposal.raw_transcript == text
    assert proposal.entities == {"application": "Spotify", "media": "Taare Zameen Par"}
    assert proposal.canonical_command == "Play Taare Zameen Par on Spotify"
    assert not proposal.requires_confirmation and not proposal.execution_permitted
