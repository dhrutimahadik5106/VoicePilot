from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.core.config import Settings
from app.commands.resolver import CommandResolver
from app.launch.authorization import VoiceAuthority
from app.launch.controller import LaunchController
from app.launch.models import Configuration, LaunchError, Status
from app.pipeline.service import DiagnosticService
from tests.pipeline.helpers import audio, STT
from tests.pipeline.test_service import verified
from tests.launch.helpers import Backend

# Load only public repository vocabulary during collection, before filesystem guards.
RESOLVER = CommandResolver.from_directory()


def settings():
    return Settings(speaker_verification_enabled=True,
                    speaker={"calibration_state": "validated"},
                    launch=Configuration(real_execution_enabled=True))


@pytest.mark.parametrize("response", [True, None])
def test_failed_authentication_never_reaches_stt(response):
    cfg = settings()
    stt = STT()
    pipeline = DiagnosticService(cfg, stt=stt, resolver=RESOLVER,
        verifier=SimpleNamespace(verify=lambda *a, **k: response))
    backend = Backend()
    authority = VoiceAuthority(cfg, backend, pipeline=pipeline)
    with pytest.raises(LaunchError):
        authority.prepare(audio(), uuid4())
    assert not stt.calls and not backend.calls


@pytest.mark.parametrize("text", ["open Notepad", "open Calculator", "open Chrome", "open Spotify"])
def test_verified_pipeline_requires_exact_confirmation(text):
    cfg = settings()
    stt = STT(text)
    pipeline = DiagnosticService(cfg, stt=stt, resolver=RESOLVER,
        verifier=SimpleNamespace(verify=verified))
    backend = Backend()
    authority = VoiceAuthority(cfg, backend, pipeline=pipeline)
    plan = authority.prepare(audio(), uuid4())
    assert stt.calls and not backend.created
    key = authority.challenge(plan, typed_application=plan.application_id)
    permit = authority.confirm(key, plan, response="LAUNCH " + plan.application_id)
    result = LaunchController(cfg.launch, backend=backend).run(plan, permit, authority)
    assert result.status == Status.LAUNCHED and backend.created == 1
    assert plan.authentication_id is not None
    assert str(plan.authentication_id) not in result.model_dump_json()


@pytest.mark.parametrize("text", ["play Spotify", "open unknownapp", "open Spotify and Chrome",
                                  "delete files", "password PRIVATE_MARKER"])
def test_non_launch_or_unsafe_voice_never_authorized(text):
    cfg = settings()
    pipeline = DiagnosticService(cfg, stt=STT(text), resolver=RESOLVER,
        verifier=SimpleNamespace(verify=verified))
    backend = Backend()
    with pytest.raises(LaunchError) as error:
        VoiceAuthority(cfg, backend, pipeline=pipeline).prepare(audio(), uuid4())
    assert not backend.calls
    assert "PRIVATE_MARKER" not in str(error.value)
