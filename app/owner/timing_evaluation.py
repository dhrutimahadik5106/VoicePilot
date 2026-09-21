"""Deterministic fake schedule; not a hardware, model or biometric benchmark."""
from types import SimpleNamespace
from app.core import timing
from app.owner.fakes import Harness
from app.owner.confirmation import ConfirmationCapture


def evaluate():
    h = Harness().calibrate()
    counts = {"speaker_initializations": 0, "stt_initializations": 0, "volume_reads": 0, "speaker_calls": 0}
    report = timing.Report(clock=lambda: h.now)
    token = timing.activate(report)
    capture, extract, transcribe = h.capture, h.extract, h.transcribe_audio
    read_volume, set_volume = h.backend.read_volume, h.backend.set_volume

    def advance(seconds):
        h.now += seconds

    def prepared_capture(phrase, session, audio_id, *, guard):
        confirmation = type(phrase) is ConfirmationCapture
        if confirmation:
            timing.begin("confirmation_enter_wait")
        elif phrase is None:
            timing.begin("command_enter_wait")
        advance(.25)
        timing.end("confirmation_enter_wait" if confirmation else
                   "phrase_display_to_enter" if phrase is not None else "command_enter_wait")
        guard()
        with timing.span("recorder_setup"):
            advance(.05)
        guard()
        with timing.span("confirmation_recording" if confirmation else
                         "capture" if phrase is not None else "command_recording"):
            advance(1.)
            return capture(phrase, session, audio_id, guard=guard)

    def speaker(audio, **kwargs):
        counts["speaker_calls"] += 1
        temperature = "warm" if counts["speaker_initializations"] else "cold"
        if temperature == "cold":
            with timing.span("speaker_model_load", "cold"):
                counts["speaker_initializations"] += 1
                advance(.5)
        with timing.span("speaker_inference", temperature):
            advance(.075)
            return extract(audio, **kwargs)

    def stt(audio, **kwargs):
        temperature = "warm" if counts["stt_initializations"] else "cold"
        load = 0. if temperature == "warm" else 1.
        counts["stt_initializations"] = 1
        advance(load + .2)
        timing.add("stt_model_load", load, temperature)
        timing.add("stt_inference", .2, temperature)
        return transcribe(audio, **kwargs)

    def observed():
        counts["volume_reads"] += 1
        advance(.025)
        return read_volume()

    def mutated(*args):
        advance(.01)
        return set_volume(*args)

    h.calibration.capture = prepared_capture
    h.calibration.present = lambda phrase: advance(.125)
    h.calibration.engine = SimpleNamespace(identity=h.identity, extract=speaker)
    h.calibration.stt = SimpleNamespace(transcribe_audio=stt)
    h.backend.read_volume, h.backend.set_volume = observed, mutated
    try:
        verified = 0
        for index in range(2):
            timing.begin("total_after_consent")
            with timing.span("runtime_initialization", "cold" if index == 0 else "warm"):
                advance(.025 if index == 0 else 0.)
            timing.begin("consent_to_phrase_display")
            result = h.pilot.run(h.profile.profile_id)
            verified += int(result.status == "completed")
            timing.end("total_after_consent")
        return {"label": "synthetic_schedule_not_real_performance", "sessions": 2,
                "verified_sessions": verified,
                "captures": h.capture_count, "stt_calls": h.stt_calls,
                **counts, "timings": report.document()}
    finally:
        timing.deactivate(token)
