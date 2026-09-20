"""Deterministic fake schedule; not a hardware, model or biometric benchmark."""
from types import SimpleNamespace
from app.core import timing
from app.owner.fakes import Harness


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
        if phrase is None:
            timing.begin("command_enter_wait")
        advance(.25)
        timing.end("phrase_display_to_enter" if phrase is not None else "command_enter_wait")
        guard()
        with timing.span("recorder_setup"):
            advance(.05)
        guard()
        with timing.span("capture" if phrase is not None else "command_capture"):
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
        timing.begin("total_after_consent")
        timing.begin("consent_to_phrase_display")
        result = h.pilot.run(h.profile.profile_id)
        timing.end("total_after_consent")
        return {"label": "synthetic_schedule_not_real_performance", "sessions": 1,
                "verified_sessions": int(result.status == "completed"),
                "captures": h.capture_count, "stt_calls": h.stt_calls,
                **counts, "timings": report.document()}
    finally:
        timing.deactivate(token)
