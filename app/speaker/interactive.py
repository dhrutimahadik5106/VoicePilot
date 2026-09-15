"""Deliberate terminal workflows; no construction starts capture."""
import os
from pathlib import Path
from threading import Event
from uuid import uuid4
import numpy as np
from app.speaker.artifacts import DEFAULT_PATH, SHA256
from app.speaker.contracts import SpeakerError
from app.speaker.models import EnrollmentConsent, ThresholdConfiguration, SpeakerProfile
from app.speaker.enrollment import EnrollmentService
from app.speaker.verification import VerificationService
from app.speaker.thresholds import BoundedThresholdPolicy
from app.speaker.quality import NumericalQuality
from app.speaker.sherpa_backend import SherpaEmbeddingEngine
from app.speaker.dpapi import DPAPIProtector
from app.speaker.profiles import ProtectedProfileRepository, default_profile_root, check_cancel
from app.speaker.private_store import private_root, provision_private_root, PrivateRecords
from app.speaker.embedding import cosine
from app.speaker.pipeline import SpeakerGateway

PHRASES = (
    "The morning sky is clear and the trees move in the breeze.",
    "I am reading a short sentence at a comfortable speaking pace.",
    "A small blue notebook rests beside a glass of water.",
    "Today I will describe a quiet walk through a garden.",
    "Several bright flowers grow near the wooden gate.")
MESSAGES = {"verified":"Voice verified.", "rejected":"Voice not recognized. Access denied.",
    "uncertain":"Voice verification was uncertain. Please try again.",
    "unavailable":"Speaker verification is unavailable.", "invalid_audio":"Audio was unusable. Please try again.",
    "invalid_profile":"Speaker profile is invalid. Access denied.", "cancelled":"Cancelled. Audio discarded."}

class LocalSpeakerSession:
    def __init__(self, settings, *, read=input, write=print, recorder=None, engine=None,
                 protector=None, root_provisioner=provision_private_root, control=None):
        self.settings, self.cfg = settings, settings.speaker
        self.read, self.write = read, write
        self.recorder, self.control = recorder, control
        self.engine = engine or SherpaEmbeddingEngine(self.cfg.model_path or DEFAULT_PATH,self.cfg)
        self.protector = protector or DPAPIProtector()
        self.provisioner = root_provisioner
        self.cancel = Event()

    def approve(self, message):
        if self.read(message+" Type yes to approve: ").strip().lower()!="yes":
            raise SpeakerError("cancelled")

    def ready(self):
        if self.cfg.checksum != SHA256:
            raise SpeakerError("model_invalid")
        self.engine.ready()
        self.protector.smoke()

    def repository(self, *, create=False):
        root=private_root(self.cfg.profile_root or default_profile_root())
        if create:
            self.provisioner(root)
        return ProtectedProfileRepository(root,self.protector)

    def records(self, *, create=False):
        if self.cfg.calibration_root:
            root=self.cfg.calibration_root
        else:
            local=os.environ.get("LOCALAPPDATA")
            if not local:
                raise SpeakerError("protection_unavailable")
            root=Path(local)/"VoicePilot"/"speaker-calibration"
        root=private_root(root)
        if create:
            self.provisioner(root)
        return PrivateRecords(root,self.protector)

    def capture(self, phrase=None):
        check_cancel(self.cancel)
        if phrase:
            self.write("Neutral prompt (not a secret): "+phrase)
        if self.read("Press Enter to START capture; type anything to cancel: ")!="":
            raise SpeakerError("cancelled")
        if self.recorder is None:
            from app.audio.recorder import SoundDeviceRecorder
            settings=self.settings.model_copy(update={"audio_sample_rate":16000,"audio_channels":1,
                "audio_max_duration_seconds":self.cfg.max_duration,"audio_silence_stop_enabled":False})
            self.recorder=SoundDeviceRecorder(settings)
        if self.control is None:
            from app.audio.cli import terminal_control
            self.control=terminal_control
        self.write("Recording. Enter stops; c or Ctrl+C cancels. Audio will not be saved.")
        duration=min(self.cfg.capture_duration,self.cfg.max_duration)
        result=self.recorder.record(duration,control=self.control)
        if result.status=="cancelled":
            raise SpeakerError("cancelled")
        if result.status!="succeeded":
            raise SpeakerError("invalid_audio")
        check_cancel(self.cancel)
        return result.audio

    def enroll(self, profile_id=None):
        self.write("Voice enrollment protects VoicePilot only, not Windows login. "
            "A protected biometric profile will be stored locally. Raw audio is not retained. "
            "Voice matching does not defeat replay or deepfakes.")
        self.approve("Consent to enroll using "+str(self.cfg.enrollment_samples)+" samples?")
        self.approve("Separately consent to protected profile persistence?")
        if profile_id is not None:
            self.approve("Replace the selected profile after successful re-enrollment?")
        self.ready()
        repo=self.repository(create=True)
        if profile_id is not None:
            repo.load(profile_id)
        samples=[]
        try:
            quality=NumericalQuality(self.cfg)
            # Retry only unusable captures; every retry starts with deliberate Enter.
            for index in range(self.cfg.enrollment_samples):
                for retry in range(self.cfg.max_retries+1):
                    try:
                        audio=self.capture(PHRASES[index])
                    except SpeakerError as error:
                        if error.code != "invalid_audio":
                            raise
                        self.write("Unusable sample discarded.")
                        continue
                    if quality.assess(audio).eligible:
                        samples.append((uuid4(),audio))
                        del audio
                        break
                    del audio
                    self.write("Unusable sample discarded.")
                else:
                    raise SpeakerError("invalid_audio")
            pending=ThresholdConfiguration(version="calibration-pending",model=self.engine.identity,
                                           acceptance=1,calibration="pending")
            result=EnrollmentService(self.cfg,self.engine,quality,repo,BoundedThresholdPolicy(pending)).enroll(
                samples,EnrollmentConsent(enrollment=True,persistence=True),cancel=self.cancel,
                profile_id=profile_id,enrollment_session=uuid4())
            if result.status=="enrolled":
                return {"status":"enrolled","profile_id":str(result.profile_id),"calibration":"pending",
                        "raw_audio_saved":False}
            return {"status":result.status,"reason":result.reason}
        finally:
            samples.clear()

    def policy(self, profile, policy_id):
        if policy_id is None:
            raise SpeakerError("calibration_pending")
        document=self.records().load(policy_id)
        if (document.get("kind")!="approved-policy" or document.get("authorization_approved") is not True
                or str(profile.profile_id) not in document.get("profiles",[])):
            raise SpeakerError("calibration_pending")
        from app.speaker.provenance import binding
        if document.get("provenance") != binding(profile):
            raise SpeakerError("incompatible_profile")
        cfg=ThresholdConfiguration.model_validate(document["policy"])
        if (cfg.calibration!="validated" or cfg.model!=self.engine.identity
                or profile.model!=cfg.model or profile.calibration!="validated"
                or profile.policy_version!=cfg.version):
            raise SpeakerError("incompatible_profile")
        return BoundedThresholdPolicy(cfg)

    def verify(self, profile_id, *, policy_id=None, diagnostics=False, command=False):
        self.ready()
        repo=self.repository()
        profile=repo.load(profile_id)
        if profile.model!=self.engine.identity:
            raise SpeakerError("incompatible_profile")
        if command:
            if not self.settings.speaker_verification_enabled:
                raise SpeakerError("unavailable")
            policy=self.policy(profile,policy_id)  # preflight BEFORE capture or STT imports
        elif policy_id is not None:
            policy=self.policy(profile,policy_id)
        else:
            policy=None
        audio=self.capture()
        try:
            if policy is None:
                score=cosine(self.engine.extract(audio,cancel=self.cancel),profile.template,profile.model.dimension)
                check_cancel(self.cancel)
                self.write("Speaker verification is unavailable. Calibration pending; access denied.")
                result={"status":"unavailable","reason":"calibration_pending","authorization_permitted":False}
                if diagnostics:
                    result["similarity_score"]=score
                return result
            verifier=VerificationService(self.engine,NumericalQuality(self.cfg),repo,policy)
            if command:
                from app.stt.service import TranscriptionService
                from app.stt.faster_whisper_engine import FasterWhisperEngine
                from app.commands.resolver import CommandResolver
                from app.commands.registry import DATA_DIR
                stt_settings=self.settings.model_copy(update={"stt_local_files_only":True})
                stt=TranscriptionService(stt_settings,FasterWhisperEngine(stt_settings))
                gateway=SpeakerGateway(verifier,stt,CommandResolver.from_directory(DATA_DIR))
                result=gateway.run(audio,profile_id,cancel=self.cancel)
                if result.verification:
                    self.write(MESSAGES[result.verification.status])
                # No transcript, canonical text or entity value printed automatically.
                return {"status":result.status,"reason":result.reason,"execution_permitted":False}
            result=verifier.verify(audio,profile_id,audio_id=uuid4(),cancel=self.cancel)
            self.write(MESSAGES[result.status])
            public={"status":result.status,"reason":result.reason,"spoof_assurance":"not_assessed"}
            if diagnostics and result.status!="cancelled" and result.similarity is not None:
                public["similarity_score"]=result.similarity
            return public
        finally:
            del audio

    def delete(self, profile_id):
        self.approve("Permanently delete the selected local profile? Backups/copies cannot be erased here.")
        self.repository().delete(profile_id)
        return {"status":"deleted","profile_id":str(profile_id)}

    def collect(self, args):
        from app.speaker.calibration import record_trial
        self.write("Calibration stores protected scores and pseudonymous metadata only. No raw audio. "
                   "Each speaker must personally consent; never collect someone secretly.")
        self.approve("Do you consent to this biometric evaluation sample and score persistence?")
        impostor=False
        if args.speaker != args.profile:
            self.approve("Does the impostor speaker give their own informed consent now?")
            impostor=True
        self.ready()
        profile=self.repository().load(args.profile)
        store=self.records(create=True)
        audio=self.capture()
        try:
            identifier=record_trial(audio,profile,self.engine,store,speaker=args.speaker,session=args.session,
                group=args.group,split=args.split,consent=True,impostor_consent=impostor,
                language=args.language,condition=args.condition,cancel=self.cancel)
            return {"status":"recorded","trial_id":str(identifier),"audio_saved":False}
        finally:
            del audio
