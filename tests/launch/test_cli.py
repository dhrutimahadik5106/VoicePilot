import json
from uuid import uuid4
import pytest
from app.core.config import Settings
from app.launch.cli import main
from app.launch.models import Status
from tests.launch.helpers import Backend


@pytest.mark.parametrize("app", ["notepad", "calculator", "chrome", "spotify"])
def test_manual_exact_consent(app):
    backend = Backend()
    answers = iter([app, "LAUNCH " + app])
    out, prompts = [], []
    def read(prompt):
        prompts.append(prompt)
        return next(answers)
    assert main(["manual-launch-test", app], backend=backend, read=read, write=out.append) == 0
    assert "not voice authentication" in out[0]
    assert len(prompts) == 2 and backend.created == 1
    assert json.loads(out[-1])["status"] == "launched_and_verified"


@pytest.mark.parametrize("answers", [["no"], ["notepad", "no"], ["notepad", "yes"], ["notepad", "LAUNCH chrome"]])
def test_declined_confirmation(answers):
    backend = Backend()
    responses = iter(answers)
    assert main(["manual-launch-test", "notepad"], backend=backend, read=lambda _: next(responses), write=lambda _: None) == 2
    assert backend.created == 0


@pytest.mark.parametrize("args", [["manual-launch-test", "PRIVATE_MARKER"], ["manual-launch-test", "C:/app.exe"],
    ["manual-launch-test", "notepad", "chrome"], ["manual-launch-test", "notepad", "--confirmed=true"],
    ["manual-launch-test", "notepad", "--args", "PRIVATE_MARKER"], ["manual-launch-test", "notepad", "--elevate"],
    ["manual-launch-test", "spotify:play"], ["manual-launch-test", "cmd"], ["discover", "PRIVATE_MARKER"]])
def test_invalid_cli_never_launches_or_echoes_private_input(args):
    out = []
    backend = Backend()
    assert main(args, backend=backend, read=lambda _: pytest.fail("unexpected_prompt"), write=out.append) == 2
    assert backend.created == 0 and "PRIVATE_MARKER" not in str(out)


@pytest.mark.parametrize("command", ["list", "status", "authenticated-voice-status", "discover"])
def test_inspection_never_launches(command):
    backend = Backend()
    out = []
    assert main([command], backend=backend, read=lambda _: pytest.fail("unexpected_prompt"), write=out.append) == 0
    assert backend.created == 0 and out
    if command != "discover":
        assert backend.calls == []


def test_missing_installation_never_asks_launch_confirmation():
    backend = Backend()
    backend.discovery = Status.NOT_INSTALLED
    prompts = []
    assert main(["manual-launch-test", "spotify"], backend=backend,
                read=lambda p: prompts.append(p) or "spotify", write=lambda _: None) == 2
    assert len(prompts) == 1 and backend.created == 0


def test_pending_voice_denies_before_microphone_stt_and_backend():
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("pending_voice_called_integration")
    out = []
    assert main(["authenticated-voice", "--profile", str(uuid4())], settings=Settings(),
                backend=Forbidden(), recorder=Forbidden(), pipeline=Forbidden(),
                read=lambda _: pytest.fail("unexpected_prompt"), write=out.append) == 2
    document = json.loads(out[-1])
    assert document["reason"] == "calibration_pending" and document["stt"] == "not_called"


def test_keyboard_interrupt_does_not_launch():
    backend = Backend()
    def cancel(_):
        raise KeyboardInterrupt()
    assert main(["manual-launch-test", "notepad"], backend=backend, read=cancel, write=lambda _: None) == 2
    assert backend.created == 0
