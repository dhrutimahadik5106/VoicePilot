"""Phase 6C regressions under the owner suite's active side-effect guards."""
import pickle
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.owner.confirmation import PendingConfirmation, ConfirmationCapture
from app.owner.models import OwnerError, Evidence
from app.owner.pilot import resolve
from app.owner.runtime import Runtime


@pytest.mark.parametrize("command", ["what is the volume", "is the computer muted", "what is the brightness", "stop", "cancel"])
def test_read_and_safety_skip_confirmation(calibrated, command):
    h = calibrated
    h.command, h.confirmation = command, "must not be consulted"
    result = h.pilot.run(h.profile.profile_id)
    assert result.status == "completed"
    assert h.capture_count == h.stt_calls == 2
    assert h.backend.mutations == h.launch_backend.launched == 0


@pytest.mark.parametrize("command", ["mute", "unmute", "volume up", "volume down", "set volume to 40 percent",
                                     "open notepad", "open calculator", "open chrome"])
@pytest.mark.parametrize("response", ["confirm", "cancel"])
def test_all_mutations_require_separate_confirmation(calibrated, command, response):
    h = calibrated
    h.command, h.confirmation = command, response
    result = h.pilot.run(h.profile.profile_id)
    assert h.capture_count == h.stt_calls == 3
    assert result.status == ("completed" if response == "confirm" else "cancelled")
    if response == "cancel":
        assert h.backend.reads == h.backend.mutations == h.launch_backend.launched == 0
    assert h.pilot._confirmation is None and not h.pilot._evidence


@pytest.mark.parametrize("response", ["", "yes", "confirmed", "confirm and mute", "cancel then confirm", "do not confirm",
    "confirm confirm", "Confirm.", "true", "The orange basket holds several fresh apples and pears"])
def test_closed_response_no_salvage(calibrated, response):
    h = calibrated
    h.confirmation = response
    result = h.pilot.run(h.profile.profile_id)
    assert result.reason == "confirmation_rejected"
    assert h.backend.reads == h.backend.mutations == h.launch_backend.launched == 0


@pytest.mark.parametrize("stage", ["command", "confirmation"])
@pytest.mark.parametrize("score", [.2, .88])
def test_speaker_before_each_stt(calibrated, stage, score):
    h = calibrated
    setattr(h, stage + "_score", score)
    result = h.pilot.run(h.profile.profile_id)
    assert result.status == "blocked"
    assert h.stt_calls == (1 if stage == "command" else 2)
    assert h.backend.reads == h.backend.mutations == h.launch_backend.launched == 0


@pytest.mark.parametrize("fault", ["expired", "profile", "environment", "cancel", "replay_command", "replay_challenge"])
def test_failure_during_confirmation_has_no_backend_call(calibrated, fault):
    h = calibrated
    captured = []
    original = h.calibration.capture
    def capture(phrase, session, audio_id, *, guard):
        if type(phrase) is ConfirmationCapture:
            if fault == "expired": h.now += 31
            if fault == "profile": h.profile = h.profile.model_copy(update={"enrollment_session": uuid4()})
            if fault == "environment": h.environment = "other-input"
            if fault == "cancel": h.pilot.cancel.set()
            guard()
            if fault.startswith("replay"):
                return captured[0 if fault == "replay_challenge" else 1]
        audio = original(phrase, session, audio_id, guard=guard)
        captured.append(audio)
        return audio
    # Keep the environment callback available through the bound original capture.
    h.calibration.capture = capture
    h.pilot._environment = lambda session: h.environment
    result = h.pilot.run(h.profile.profile_id)
    assert result.status in {"blocked", "cancelled"}
    assert h.backend.reads == h.backend.mutations == h.launch_backend.launched == 0
    assert h.stt_calls == 2
    assert h.pilot._confirmation is None and not h.pilot._evidence


@pytest.mark.parametrize("fault", ["plan", "text", "session", "profile", "environment", "expiry", "policy"])
def test_private_confirmation_binding_and_consume_on_failed_attempt(fault):
    plan, text = resolve("set volume to 40 percent"), "set volume to 40 percent"
    context = (uuid4(), uuid4(), "synthetic-environment")
    pending = PendingConfirmation(plan, text, context, 30.)
    candidate, command, selected, clock = plan, text, context, 0.
    if fault == "plan": candidate = plan.model_copy(update={"percentage": 41})
    if fault == "text": command = "mute"
    if fault in {"session", "profile", "environment"}:
        values = list(context)
        values[{"session": 0, "profile": 1, "environment": 2}[fault]] = "changed"
        selected = tuple(values)
    if fault == "expiry": clock = 30.
    if fault == "policy": pending._policy = "changed"
    with pytest.raises(OwnerError):
        pending.consume(candidate, command, selected, clock)
    with pytest.raises(OwnerError, match="confirmation_replayed"):
        pending.consume(plan, text, context, 0.)


def test_private_confirmation_single_use_and_privacy():
    plan = resolve("mute")
    pending = PendingConfirmation(plan, "mute", (uuid4(),), 30.)
    assert repr(pending) == "PendingConfirmation()"
    with pytest.raises(OwnerError): pickle.dumps(pending)
    assert "mute" not in repr(ConfirmationCapture("mute"))
    context = pending._context
    pending.consume(plan, "mute", context, 0.)
    with pytest.raises(OwnerError): pending.consume(plan, "mute", context, 0.)


@pytest.mark.parametrize("fault", ["arguments", "expiry", "environment", "profile"])
def test_mutation_after_confirmation_denied_before_backend(calibrated, monkeypatch, fault):
    h = calibrated
    h.command = "set volume to 41 percent"
    original = h.pilot.operations.run
    def changed(plan, permit, authority, **kwargs):
        if fault == "arguments": plan = plan.model_copy(update={"percentage": 99})
        if fault == "expiry": h.now += 31
        if fault == "environment": h.environment = "changed"
        if fault == "profile": h.profile = h.profile.model_copy(update={"enrollment_session": uuid4()})
        return original(plan, permit, authority, **kwargs)
    monkeypatch.setattr(h.pilot.operations, "run", changed)
    result = h.pilot.run(h.profile.profile_id)
    assert result.status == "blocked" and h.capture_count == h.stt_calls == 3
    assert h.backend.reads == h.backend.mutations == 0


@pytest.mark.parametrize("value", [True, "confirm", {}, Evidence()])
def test_text_boolean_or_forged_evidence_never_authorizes(calibrated, value):
    with pytest.raises(OwnerError): calibrated.pilot.command(value, uuid4())
    assert calibrated.capture_count == calibrated.stt_calls == calibrated.backend.reads == 0


@pytest.mark.parametrize("fault", ["model", "stt", "cancel", "buffer"])
def test_confirmation_terminal_cleanup(calibrated, fault):
    h = calibrated
    extract, stt = h.engine.extract, h.transcribe_audio
    def speaker(audio, **kwargs):
        if h.capture_count == 3 and fault == "model": raise RuntimeError("PRIVATE")
        if h.capture_count == 3 and fault == "cancel": h.pilot.cancel.set()
        return extract(audio, **kwargs)
    def transcribe(audio, **kwargs):
        if h.capture_count == 3 and fault == "stt": raise RuntimeError("PRIVATE")
        result = stt(audio, **kwargs)
        if h.capture_count == 3 and fault == "buffer":
            audio.samples.flags.writeable = True
            audio.samples[:] = 0
        return result
    h.engine.extract = speaker
    h.calibration.stt = SimpleNamespace(transcribe_audio=transcribe)
    result = h.pilot.run(h.profile.profile_id)
    assert result.status != "completed"
    assert h.backend.reads == h.backend.mutations == 0
    assert not h.pilot._lock.locked() and not h.hub._active
    assert not h.challenges.pending and h.pilot._confirmation is None
    assert "PRIVATE" not in result.model_dump_json() + repr(result)


def test_runtime_confirmation_display_and_environment_cleanup(harness):
    output = []
    runtime = Runtime(harness.settings, read=lambda _: "cancel", write=output.append)
    session = uuid4()
    runtime._devices[session] = (1, "private-input", 1, 16000)
    with pytest.raises(OwnerError, match="cancelled"):
        runtime.capture(ConfirmationCapture("system.volume.mute. Say only Confirm or Cancel."),
                        session, uuid4(), guard=lambda: None)
    assert len(output) == 1 and "private-input" not in output[0]
    runtime.release_session(session)
    assert not runtime._devices


@pytest.mark.parametrize("stage", ["challenge", "command", "confirmation"])
def test_expiry_during_speaker_inference_prevents_stt(calibrated, stage):
    h = calibrated
    extract = h.engine.extract
    count = {"challenge": 1, "command": 2, "confirmation": 3}[stage]
    def delayed(audio, **kwargs):
        result = extract(audio, **kwargs)
        if h.capture_count == count:
            h.now += 100
        return result
    h.engine.extract = delayed
    result = h.pilot.run(h.profile.profile_id)
    assert result.status == "blocked"
    assert h.stt_calls == count - 1
    assert h.backend.reads == h.backend.mutations == h.launch_backend.launched == 0


def test_prior_challenge_audio_replay_rejected(calibrated):
    h = calibrated
    first = h.pilot.authenticate(h.profile.profile_id, uuid4())
    assert first.status == "accepted"
    h.reuse = True
    second = h.pilot.authenticate(h.profile.profile_id, uuid4())
    assert second.reason == "duplicate_sample"
    assert h.stt_calls == 1 and h.backend.reads == 0
