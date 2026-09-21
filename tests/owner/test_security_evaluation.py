"""Numerator/denominator checks and guarded CLI entry points, synthetic inputs only."""
import json
from uuid import uuid4

import pytest

from app.owner.cli import main
from app.owner.security_evaluation import usability, threats, CASES, Threat
from app.owner.confirmation import policy_document
from app.owner.timing_evaluation import evaluate


def test_usability_exact_denominators():
    report = usability()
    m = report["metrics"]
    assert len(CASES) == report["cases"] == 22
    assert m["command_resolution_correctness"] == {"numerator": 13, "denominator": 13}
    assert m["safe_rejection_correctness"] == {"numerator": 9, "denominator": 9}
    assert m["false_execution"] == m["privacy_violations"] == {"numerator": 0, "denominator": 22}
    assert m["fake_only_enforcement"] == {"numerator": 22, "denominator": 22}


def test_threat_denominators_and_honest_spoof_limitations():
    report = threats()
    m = report["metrics"]
    assert report["cases"] == len(Threat) == 14
    assert m["threat_rejection"] == {"numerator": 11, "denominator": 11}
    assert m["false_execution"] == {"numerator": 0, "denominator": 11}
    assert m["adversarial_effects"] == {"numerator": 3, "denominator": 14}
    assert m["labelled_spoof_stress_acceptance"] == {"numerator": 3, "denominator": 3}
    assert m["replay_rejection"] == {"numerator": 3, "denominator": 3}
    assert m["authorization_bypass"] == {"numerator": 0, "denominator": 4}
    assert m["confirmation_bypass"] == {"numerator": 0, "denominator": 5}
    for name in ("authentication_before_stt", "command_speaker_recheck", "confirmation_speaker_recheck"):
        assert m[name] == {"numerator": 1, "denominator": 1}
    assert all(row["detection_claim"] is False for row in report["outcomes"])


@pytest.mark.parametrize("command", ["inspect-config", "confirmation-policy", "evaluate-usability", "evaluate-threats", "evaluate-timings", "evaluate-all"])
def test_safe_cli_no_runtime_or_profile(command):
    output = []
    def forbidden(*args, **kwargs):
        pytest.fail("runtime_access")
    assert main([command], factory=forbidden, write=output.append) == 0
    document = json.loads(output[-1])
    assert document
    assert not any(word in output[-1] for word in ("raw_transcript", "provenance", "PRIVATE"))
    assert main([command, "--profile", str(uuid4())], factory=forbidden, write=output.append) == 2


def test_policy_is_fixed_not_enabling_configuration():
    policy = policy_document()
    assert policy["responses"] == ["confirm", "cancel"]
    assert policy["confirmation_seconds"] == 30
    assert policy["extends_authentication"] is False


def test_timing_has_separate_confirmation_and_fresh_inference():
    report = evaluate()
    assert report["captures"] == report["stt_calls"] == report["speaker_calls"] == 6
    assert report["speaker_initializations"] == report["stt_initializations"] == 1
    rows = report["timings"]["samples"]
    assert {row["stage"] for row in rows} >= {"challenge_preparation", "challenge_speaker_inference",
        "command_speaker_inference", "confirmation_capture", "confirmation_speaker_inference", "confirmation_stt",
        "authorization", "total_session"}
    assert all(set(row) == {"stage", "seconds", "temperature", "completed"} for row in rows)
