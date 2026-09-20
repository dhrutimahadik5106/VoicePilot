import json
from types import SimpleNamespace
import pytest
from app.owner.cli import main
from app.core.config import Settings
from app.owner.evaluation import evaluate


@pytest.mark.parametrize("args", [["inspect-config"], ["privacy"], ["voice-pilot", "--profile", "00000000-0000-0000-0000-000000000001"]])
def test_safe_default_commands_no_runtime(args):
    def forbidden(*a, **k):
        pytest.fail("runtime_constructed")
    output = []
    result = main(args, factory=forbidden, write=output.append, interactive=lambda: True)
    assert result == (2 if args[0] == "voice-pilot" else 0)


@pytest.mark.parametrize("args", [["voice-pilot", "--profile", "PRIVATE_MARKER"], ["begin", "--confirmed=true"],
                                  ["owner", "--profile", "PRIVATE_MARKER"]])
def test_bad_arguments_not_echoed(args):
    output = []
    assert main(args, write=output.append) == 2
    assert "PRIVATE_MARKER" not in str(output)


def test_noninteractive_no_runtime(harness):
    def forbidden(*a, **k):
        pytest.fail("runtime_constructed")
    assert main(["begin", "--profile", str(harness.profile.profile_id)], settings=harness.settings,
                factory=forbidden, write=lambda _: None, interactive=lambda: False) == 2


def test_explicit_begin_and_resume(harness):
    runtime = SimpleNamespace(calibration=lambda: harness.calibration)
    output = []
    key = str(harness.profile.profile_id)
    for command in ("begin", "resume", "status", "results"):
        assert main([command, "--profile", key], settings=harness.settings, factory=lambda *a, **k: runtime,
            read=lambda _: "CONSENT BEGIN", write=output.append, interactive=lambda: True) == 0
    assert json.loads(output[-1])["owner_count"] == 0


def test_pilot_cli_uses_only_fake_services(calibrated):
    runtime = SimpleNamespace(calibration=lambda: calibrated.calibration, pilot=lambda _: calibrated.pilot)
    output = []
    assert main(["voice-pilot", "--profile", str(calibrated.profile.profile_id)], settings=calibrated.settings,
        factory=lambda *a, **k: runtime, read=lambda _: "CONSENT VOICE-PILOT", write=output.append,
        interactive=lambda: True) == 0
    assert json.loads(output[-1])["status"] == "completed"
    assert "raw_command" not in output[-1]


def test_synthetic_evaluation_denominators():
    metrics = evaluate()["metrics"]
    expected = {"genuine_accepted": (2,4), "genuine_retry_or_uncertain": (1,4), "genuine_rejected": (1,4),
        "impostor_accepted": (1,4), "impostor_retry_or_uncertain": (1,4), "impostor_rejected": (2,4),
        "replay_challenge_rejection": (4,4), "expired_evidence_rejection": (1,1),
        "authorization_bypasses": (0,3), "execution_after_failed_authentication": (0,6),
        "privacy_violations": (0,14), "fake_only_enforcement": (14,14)}
    assert metrics == {key: {"numerator": n, "denominator": d} for key, (n,d) in expected.items()}



@pytest.mark.parametrize("command", ["owner", "holdout", "nonowner", "replay", "freeze", "evaluate", "approve", "suspend", "revoke", "delete"])
def test_documented_cli_forms_dispatch_only_after_exact_consent(harness, command):
    calls = []
    key = str(harness.profile.profile_id)
    service = SimpleNamespace(
        collect=lambda *a, **k: calls.append(("collect", a, k)) or {"state": "test"},
        freeze=lambda *a: calls.append(("freeze", a, {})) or {"state": "test"},
        evaluate=lambda *a: calls.append(("evaluate", a, {})) or {"state": "test"},
        approve=lambda *a, **k: calls.append(("approve", a, k)) or {"state": "test"},
        change=lambda *a, **k: calls.append(("change", a, k)) or {"state": "test"})
    args = [command, "--profile", key]
    if command in {"owner", "holdout", "nonowner", "replay"}:
        args += ["--environment", "quiet"]
    if command == "nonowner":
        args += ["--participant", "00000000-0000-0000-0000-000000000010"]
    answer = "CONSENT " + command.upper() + (" " + key if command == "delete" else "")
    answers = iter([answer, "I CONSENT TO THIS TRIAL"])
    runtime = SimpleNamespace(calibration=lambda: service)
    assert main(args, settings=harness.settings, factory=lambda *a, **k: runtime,
        read=lambda _: next(answers), write=lambda _: None, interactive=lambda: True) == 0
    assert len(calls) == 1
    calls.clear()
    assert main(args, settings=harness.settings, factory=lambda *a, **k: runtime,
        read=lambda _: "yes", write=lambda _: None, interactive=lambda: True) == 2
    assert not calls
