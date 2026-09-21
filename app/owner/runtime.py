"""Explicit local wiring; constructing these dependencies never captures or loads models."""
from app.owner.models import OwnerError
from app.owner.confirmation import ConfirmationCapture
from app.core import timing
from app.owner.calibration import Calibration
from app.owner.storage import Store
from app.speaker.interactive import LocalSpeakerSession


class Runtime:
    @timing.timed("runtime_initialization")
    def __init__(self, settings, *, read=input, write=print):
        self.settings, self.read, self.write = settings, read, write
        self.local = LocalSpeakerSession(settings, read=read, write=write)
        self._stt = None
        self._devices = {}

    def transcribe_audio(self, audio, *, audio_id, cancel=None):
        if self._stt is None:
            from app.stt.service import TranscriptionService
            from app.stt.faster_whisper_engine import FasterWhisperEngine
            config = self.settings.model_copy(update={"stt_local_files_only": True})
            self._stt = TranscriptionService(config, FasterWhisperEngine(config))
        result = self._stt.transcribe_audio(audio, audio_id=audio_id, cancel=cancel)
        temperature = "cold" if result.cold_start is True else "warm" if result.cold_start is False else "not_applicable"
        timing.add("stt_model_load", result.model_load_duration, temperature)
        timing.add("stt_inference", result.inference_duration, temperature)
        return result

    def present_challenge(self, phrase):
        self.write("Speak this public challenge phrase: " + phrase)

    def capture(self, phrase, session, audio_id, *, guard):
        guard()
        confirmation = type(phrase) is ConfirmationCapture
        if confirmation:
            self.write(phrase.message)
            timing.begin("confirmation_enter_wait")
        elif phrase is None:
            self.write("Authentication accepted. Speak ONE allowlisted command; this can execute a real action.")
            timing.begin("command_enter_wait")
        try:
            if self.read("Microphone capture next. Press Enter to begin; any other input cancels: ") != "":
                raise OwnerError("cancelled")
        finally:
            timing.end("confirmation_enter_wait" if confirmation else
                       "phrase_display_to_enter" if phrase is not None else "command_enter_wait")
        guard()  # Do not start capture after an expired wait at the prompt.
        with timing.span("recorder_setup"):
            from app.audio.recorder import SoundDeviceRecorder
            from app.audio.cli import terminal_control
            if len(self._devices) >= 128 and session not in self._devices:
                raise OwnerError("access_denied")
            selected = self._devices.get(session)
            cfg = self.settings.model_copy(update={"audio_input_device": selected[0] if selected else self.settings.audio_input_device,
                "audio_sample_rate": 16000, "audio_channels": 1,
                "audio_max_duration_seconds": self.settings.speaker.max_duration,
                "audio_silence_stop_enabled": False})
            self.write("Recording; Enter stops, c or Ctrl+C cancels. Raw audio is not saved.")
            recorder = SoundDeviceRecorder(cfg)
        guard()  # Setup/display can take time; check immediately before device access.
        result = recorder.record(min(self.settings.speaker.capture_duration,
            self.settings.speaker.max_duration), control=terminal_control, guard=guard,
            capture_stage="confirmation_recording" if confirmation else
                          "capture" if phrase is not None else "command_recording")
        guard()
        if result.status != "succeeded":
            raise OwnerError("cancelled" if result.status == "cancelled" else "capture_quality_failed")
        device = result.device
        if device is None:
            raise OwnerError("binding_mismatch")
        identity = (device.index, device.name, device.max_input_channels, device.default_sample_rate)
        if selected is not None and identity != selected:
            raise OwnerError("binding_mismatch")
        self._devices[session] = identity
        return result.audio

    def environment_token(self, session):
        return self._devices.get(session)

    def release_session(self, session):
        self._devices.pop(session, None)

    def calibration(self):
        return Calibration(self.settings, self.local.repository(), Store(), self.local.engine,
                           self, self.capture, cancel=self.local.cancel, present=self.present_challenge)

    def pilot(self, calibration):
        from app.owner.pilot import Pilot
        from app.operations.controller import Controller
        from app.launch.controller import LaunchController
        return Pilot(calibration, Controller(self.settings.operations), LaunchController(self.settings.launch))
