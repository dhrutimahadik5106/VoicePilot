from uuid import uuid4
import pytest
from app.owner.models import OwnerError, Evidence
from app.owner.pilot import resolve
from app.owner.authorization import OperationAuthority, LaunchAuthority


@pytest.mark.parametrize("command", ["Open Notepad.", "Open Calculator.", "Open Chrome.",
    "What is the volume?", "Increase volume.", "Decrease volume.", "Set volume to 40 percent.",
    "Mute.", "Unmute.", "What is the brightness?", "Stop.", "Cancel."])
def test_allowed_one_command(calibrated, command):
    calibrated.command = command
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "completed", result
    captures = 2 if command in {"What is the volume?", "What is the brightness?", "Stop.", "Cancel."} else 3
    assert calibrated.capture_count == calibrated.stt_calls == captures
    assert calibrated.backend.mutations + calibrated.launch_backend.launched <= 1
    assert "raw_command" not in result.model_dump_json() + repr(result)


@pytest.mark.parametrize("score,status", [(.95,"accepted"), (.88,"retry_or_uncertain"), (.2,"rejected")])
def test_three_way(calibrated, score, status):
    calibrated.score = score
    result = calibrated.pilot.authenticate(calibrated.profile.profile_id, uuid4())
    assert result.status == status
    assert "similarity" not in result.model_dump_json()


@pytest.mark.parametrize("fault", ["speaker", "phrase", "command_speaker", "expired", "session", "profile"])
def test_failure_stops_downstream(calibrated, fault):
    if fault == "speaker":
        calibrated.score = .2
    elif fault == "phrase":
        calibrated.phrase_wrong = True
    elif fault == "command_speaker":
        calibrated.command_score = .2
    elif fault == "expired":
        def before():
            if calibrated.capture_count:
                calibrated.now = 100
        calibrated.before_capture = before
    elif fault == "profile":
        def changed():
            if calibrated.capture_count:
                calibrated.profile = calibrated.profile.model_copy(update={"enrollment_session": uuid4()})
        calibrated.before_capture = changed
    else:
        session = uuid4()
        auth = calibrated.pilot.authenticate(calibrated.profile.profile_id, session)
        with pytest.raises(OwnerError):
            calibrated.pilot.command(auth.evidence, uuid4())
        assert calibrated.stt_calls == 1
        return
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked"
    assert calibrated.stt_calls == (0 if fault == "speaker" else 1)
    assert calibrated.backend.mutations == calibrated.launch_backend.launched == 0


@pytest.mark.parametrize("text", ["open spotify", "take a screenshot", "delete screenshot", "open notepad and mute",
    "do not mute", "shutdown", "set volume to -1 percent", "set volume to 101 percent", "open C:/private",
    "set volume to 40 50 percent", "increase brightness", "import os", "mute then unmute", "confirmed=true"])
def test_disallowed_commands(text):
    with pytest.raises(OwnerError):
        resolve(text)


def test_pending_before_capture(harness):
    result = harness.pilot.run(harness.profile.profile_id)
    assert result.status == "blocked" and harness.capture_count == harness.stt_calls == 0


def test_authentication_replay(calibrated):
    session = uuid4()
    auth = calibrated.pilot.authenticate(calibrated.profile.profile_id, session)
    assert calibrated.pilot.command(auth.evidence, session).status == "completed"
    with pytest.raises(OwnerError, match="authentication_replayed"):
        calibrated.pilot.command(auth.evidence, session)
    assert calibrated.backend.mutations == 1


def test_no_direct_diagnostic_or_boolean_authority(calibrated):
    plan = resolve("mute")
    for fake in (True, {}, Evidence(), object()):
        with pytest.raises(OwnerError):
            OperationAuthority(fake, plan)
    with pytest.raises(OwnerError):
        OperationAuthority(calibrated.pilot, plan)
    assert calibrated.backend.mutations == 0



def test_no_resolver_after_authentication_failure(calibrated, monkeypatch):
    import app.owner.pilot as module
    calibrated.score = .2
    def forbidden(*args):
        pytest.fail("resolver_called_after_denial")
    monkeypatch.setattr(module, "resolve", forbidden)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked" and calibrated.capture_count == 1 and calibrated.stt_calls == 0


def test_command_buffer_substitution_rejected(calibrated):
    def mutate():
        if calibrated.capture_count == 2:
            calibrated.last_audio.samples.flags.writeable = True
            calibrated.last_audio.samples[:] = 0
    calibrated.after_stt = mutate
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.reason == "binding_mismatch" and calibrated.backend.mutations == 0


def test_stop_invalidates_existing_authentication(calibrated):
    session = uuid4()
    result = calibrated.pilot.authenticate(calibrated.profile.profile_id, session)
    calibrated.hub.cancel(emergency=True)
    with pytest.raises(OwnerError):
        calibrated.pilot.command(result.evidence, session)
    assert calibrated.capture_count == 1 and calibrated.backend.mutations == 0


def test_expired_evidence_consumed_once(calibrated):
    session = uuid4()
    result = calibrated.pilot.authenticate(calibrated.profile.profile_id, session)
    calibrated.now = 100
    with pytest.raises(OwnerError, match="authentication_expired"):
        calibrated.pilot.command(result.evidence, session)
    with pytest.raises(OwnerError, match="authentication_replayed"):
        calibrated.pilot.command(result.evidence, session)



@pytest.mark.parametrize("text", ["take a screenshot", "open spotify", "mute and unmute", "do not mute", "shutdown", "open C:/private"])
def test_unsupported_pipeline_has_no_effect(calibrated, text):
    calibrated.command = text
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.reason == "unsupported_command"
    assert calibrated.backend.mutations == calibrated.launch_backend.launched == 0


def test_exact_percentage_substitution_denied(calibrated, monkeypatch):
    calibrated.command = "set volume to 40 percent"
    driver = calibrated.pilot.operations
    original = driver.run
    def changed(plan, permit, authority, **kwargs):
        return original(plan.model_copy(update={"percentage": 90}), permit, authority, **kwargs)
    monkeypatch.setattr(driver, "run", changed)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked" and calibrated.backend.mutations == 0


def test_launch_identity_substitution_denied(calibrated, monkeypatch):
    calibrated.command = "open notepad"
    driver = calibrated.pilot.launch
    original = driver.run
    def changed(plan, permit, authority, **kwargs):
        return original(plan.model_copy(update={"identity": "b" * 64}), permit, authority, **kwargs)
    monkeypatch.setattr(driver, "run", changed)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked" and calibrated.launch_backend.launched == 0


def test_revocation_immediately_before_controller_blocks(calibrated, monkeypatch):
    driver = calibrated.pilot.operations
    original = driver.run
    def revoked(*args, **kwargs):
        calibrated.calibration.change(calibrated.profile.profile_id, "revoke", consent=True)
        return original(*args, **kwargs)
    monkeypatch.setattr(driver, "run", revoked)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked" and calibrated.backend.mutations == 0



@pytest.mark.parametrize("command,field,value", [("what is the volume", "volume_percent", 40),
    ("what is the brightness", "brightness_percent", 50), ("mute", "muted", True)])
def test_verified_readings_are_presented_without_private_evidence(calibrated, command, field, value):
    calibrated.command = command
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    public = result.model_dump(mode="json")
    assert public[field] == value
    assert not any(key in public for key in ("similarity", "provenance", "details", "transcript"))


def test_keyboard_interrupt_invalidates_session(calibrated):
    def interrupted():
        raise KeyboardInterrupt()
    calibrated.before_capture = interrupted
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "cancelled" and calibrated.pilot.cancel.is_set()
    assert calibrated.backend.mutations == 0

@pytest.mark.parametrize("target", ["operations", "launch"])
def test_synthetic_calibration_cannot_reach_real_backend(calibrated, target):
    # Constructors are inert; side-effect guards would fail any actual native access.
    if target == "operations":
        from app.operations.controller import Controller
        calibrated.pilot.operations = Controller(calibrated.settings.operations)
    else:
        from app.launch.controller import LaunchController
        calibrated.pilot.launch = LaunchController(calibrated.settings.launch)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.reason == "model_mismatch"
    assert calibrated.capture_count == calibrated.stt_calls == 0


@pytest.mark.parametrize("target", ["operations", "launch"])
@pytest.mark.parametrize("fault", ["missing", "invalid", "backend_changed"])
def test_controller_synthetic_boundary_before_backend(calibrated, monkeypatch, target, fault):
    calibrated.command = "open notepad" if target == "launch" else "increase volume"
    driver = getattr(calibrated.pilot, target)
    original = driver.run
    backend_calls = []

    class ForbiddenBackend:
        fake = False

        def __getattr__(self, name):
            backend_calls.append(name)
            raise AssertionError("backend_access_after_denial")

    def changed(plan, permit, authority, **kwargs):
        assert authority.synthetic is True
        if fault == "missing":
            del authority.synthetic
        elif fault == "invalid":
            authority.synthetic = "false"
        driver.backend = ForbiddenBackend()
        # Isolate the controller boundary from the independent pilot guard.
        authority._guard = lambda: None
        result = original(plan, permit, authority, **kwargs)
        code = result.status if target == "launch" else result.code
        assert code.value == "access_denied"
        return result

    monkeypatch.setattr(driver, "run", changed)
    result = calibrated.pilot.run(calibrated.profile.profile_id)
    assert result.status == "blocked"
    assert backend_calls == []
    assert calibrated.backend.mutations == calibrated.launch_backend.launched == 0


def test_native_backends_never_declare_fake():
    from app.launch.windows import WindowsBackend as LaunchBackend
    from app.operations.windows import WindowsBackend as OperationsBackend

    assert getattr(LaunchBackend(), "fake", False) is False
    assert OperationsBackend().fake is False
