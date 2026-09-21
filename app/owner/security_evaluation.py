"""Closed synthetic fixtures, numerical reports; no external inputs or native runtime."""
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

import numpy as np

from app.audio.models import RecordedAudio
from app.owner.confirmation import ConfirmationCapture
from app.owner.fakes import Harness
from app.owner.models import OwnerError, PilotResult
from app.owner.pilot import resolve
from app.owner.authorization import OperationAuthority


class Threat(StrEnum):
    CHALLENGE_REPLAY = "challenge_replay"
    COMMAND_REPLAY = "command_replay"
    WRONG_CHALLENGE = "wrong_challenge_speaker"
    WRONG_COMMAND = "wrong_command_speaker"
    WRONG_CONFIRMATION = "wrong_confirmation_speaker"
    STALE_CHALLENGE = "stale_challenge"
    STALE_CONFIRMATION = "stale_confirmation"
    AUTHORIZATION_REUSE = "authorization_reuse"
    PROFILE = "profile_substitution"
    SESSION = "session_substitution"
    ENVIRONMENT = "environment_substitution"
    HIGH_SIMILARITY = "high_similarity_impostor"
    CLONE = "cloned_voice_label"
    VIRTUAL = "virtual_audio_label"


@dataclass(frozen=True)
class Case:
    name: str
    text: str = field(repr=False)
    accepted: bool = True
    fault: str = "none"


CASES = (
    Case("mute", "mute"), Case("unmute", "unmute"), Case("stop", "stop"), Case("cancel", "cancel"),
    Case("notepad", "open notepad"), Case("calculator", "open calculator"), Case("chrome", "open chrome"),
    Case("up", "volume up"), Case("down", "volume down"), Case("exact", "set volume to 40 percent"),
    Case("volume", "what is the volume"), Case("brightness", "what is the brightness"),
    Case("mute_status", "is the computer muted"),
    Case("silence", "mute", False, "silence"), Case("truncated", "mute", False, "truncated"),
    Case("repetition", "mute mute mute mute mute mute", False), Case("unknown", "open unknown", False),
    Case("ambiguous", "open note", False), Case("compound", "mute and open notepad", False),
    Case("unsupported", "play music", False), Case("cross_contamination", "", False, "phrase"),
    Case("different_speaker", "mute", False, "speaker"),
)


def tally(metrics, name, value):
    entry = metrics.setdefault(name, {"numerator": 0, "denominator": 0})
    entry["numerator"] += int(value)
    entry["denominator"] += 1


def privacy(result):
    public = result.model_dump_json() + repr(result)
    return any(marker in public for marker in ("raw_command", "transcript", "provenance", "similarity", "PRIVATE"))


def usability():
    metrics = {}
    for case in CASES:
        h = Harness().calibrate()
        h.command = case.text
        if case.fault == "speaker": h.command_score = .2
        original = h.calibration.capture
        def capture(phrase, session, audio_id, *, guard):
            audio = original(phrase, session, audio_id, guard=guard)
            if phrase is None and case.fault in {"silence", "truncated"}:
                samples = np.zeros_like(audio.samples) if case.fault == "silence" else audio.samples[:8000].copy()
                audio = RecordedAudio(format=audio.format, samples=samples)
            if phrase is None and case.fault == "phrase":
                h.audio_text[id(audio)] = "Seven bright flowers grow near the little wooden gate"
            return audio
        h.calibration.capture = capture
        result = h.pilot.run(h.profile.profile_id)
        correct = (result.status == "completed") == case.accepted
        tally(metrics, "end_to_end_expected_outcome", correct)
        if case.accepted:
            expected = {"mute": "system.volume.mute", "unmute": "system.volume.unmute",
                "stop": "execution.stop", "cancel": "execution.cancel", "notepad": "notepad",
                "calculator": "calculator", "chrome": "chrome", "up": "system.volume.increase",
                "down": "system.volume.decrease", "exact": "system.volume.set", "volume": "system.volume.read",
                "brightness": "system.brightness.read", "mute_status": "system.volume.mute.read"}[case.name]
            resolved = result.details is not None and result.details["canonical_command"] == expected
            if case.name == "exact": resolved = resolved and result.details["plan"].percentage == 40
            tally(metrics, "command_resolution_correctness", correct and resolved)
        else: tally(metrics, "safe_rejection_correctness", correct)
        tally(metrics, "false_execution", not case.accepted and bool(h.backend.mutations or h.launch_backend.launched))
        tally(metrics, "privacy_violations", privacy(result))
        tally(metrics, "fake_only_enforcement", h.backend.fake is True and h.launch_backend.fake is True)
    return {"label": "synthetic_usability_not_speech_accuracy", "cases": len(CASES), "metrics": metrics}


def threats():
    metrics = {}
    outcomes = []
    for threat in Threat:
        h = Harness().calibrate()
        if threat == Threat.WRONG_CHALLENGE: h.score = .2
        if threat == Threat.WRONG_COMMAND: h.command_score = .2
        if threat == Threat.WRONG_CONFIRMATION: h.confirmation_score = .2
        captured = []
        original = h.calibration.capture
        def capture(phrase, session, audio_id, *, guard):
            if threat == Threat.STALE_CHALLENGE and not captured: h.now += 46
            if threat == Threat.STALE_CONFIRMATION and type(phrase) is ConfirmationCapture: h.now += 31
            if captured and threat == Threat.PROFILE:
                h.profile = h.profile.model_copy(update={"enrollment_session": uuid4()})
            if captured and threat == Threat.ENVIRONMENT: h.environment = "changed-input"
            guard()
            if captured and threat == Threat.CHALLENGE_REPLAY: return captured[0]
            if len(captured) == 2 and threat == Threat.COMMAND_REPLAY: return captured[1]
            audio = original(phrase, session, audio_id, guard=guard)
            captured.append(audio)
            return audio
        h.calibration.capture = capture
        h.pilot._environment = lambda session: h.environment
        if threat == Threat.CHALLENGE_REPLAY:
            first = h.pilot.authenticate(h.profile.profile_id, uuid4())
            assert first.status == "accepted"
            replay = h.pilot.authenticate(h.profile.profile_id, uuid4())
            result = PilotResult(status="blocked" if replay.status != "accepted" else "completed", reason=replay.reason)
            h.pilot._evidence.clear()
        elif threat in {Threat.SESSION, Threat.AUTHORIZATION_REUSE}:
            session = uuid4()
            auth = h.pilot.authenticate(h.profile.profile_id, session)
            if threat == Threat.AUTHORIZATION_REUSE:
                h.confirmation = "cancel"
                try: h.pilot.command(auth.evidence, session)
                except OwnerError: pass
                h.confirmation = "confirm"
            try:
                result = h.pilot.command(auth.evidence, uuid4() if threat == Threat.SESSION else session)
            except OwnerError as error:
                result = PilotResult(status="blocked", reason=error.code)
        else:
            result = h.pilot.run(h.profile.profile_id)
        limitation = threat in {Threat.HIGH_SIMILARITY, Threat.CLONE, Threat.VIRTUAL}
        accepted = result.status == "completed"
        tally(metrics, "adversarial_effects", bool(h.backend.mutations or h.launch_backend.launched))
        if limitation:
            # Labels cannot be evidence of spoofing: intentionally show this limitation.
            tally(metrics, "labelled_spoof_stress_acceptance", accepted)
        else:
            tally(metrics, "threat_rejection", not accepted)
            tally(metrics, "false_execution", bool(h.backend.mutations or h.launch_backend.launched))
        if threat in {Threat.CHALLENGE_REPLAY, Threat.COMMAND_REPLAY, Threat.AUTHORIZATION_REUSE}:
            tally(metrics, "replay_rejection", not accepted)
        if threat == Threat.WRONG_CHALLENGE: tally(metrics, "authentication_before_stt", h.stt_calls == 0)
        if threat == Threat.WRONG_COMMAND: tally(metrics, "command_speaker_recheck", h.stt_calls == 1)
        if threat == Threat.WRONG_CONFIRMATION: tally(metrics, "confirmation_speaker_recheck", h.stt_calls == 2)
        tally(metrics, "privacy_violations", privacy(result))
        tally(metrics, "fake_only_enforcement", h.backend.fake is True and h.launch_backend.fake is True)
        outcomes.append({"case": threat.value, "accepted": accepted, "detection_claim": False})
    for value in (True, "confirm", {}, object()):
        h = Harness().calibrate()
        bypass = False
        try:
            OperationAuthority(value, resolve("mute"))
            bypass = True
        except OwnerError:
            pass
        tally(metrics, "authorization_bypass", bypass)
    for response in ("cancel", "", "yes", "confirm and mute", "confirm confirm"):
        h = Harness().calibrate()
        h.confirmation = response
        result = h.pilot.run(h.profile.profile_id)
        tally(metrics, "confirmation_bypass", bool(h.backend.mutations or h.launch_backend.launched))
        tally(metrics, "confirmation_enforcement", result.status != "completed")
    return {"label": "synthetic_threats_not_real_spoof_detection", "cases": len(Threat),
            "metrics": metrics, "outcomes": outcomes}


def evaluate_all():
    from app.owner.timing_evaluation import evaluate
    return {"usability": usability(), "threats": threats(), "timings": evaluate()}
