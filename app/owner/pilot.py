"""Fresh challenge, separate speaker-checked command capture, exact one-command execution."""
from time import monotonic
from threading import Event, Lock
from uuid import uuid4, UUID
from app.core import timing
from app.owner.models import Outcome, Evidence, PilotResult, OwnerError
from app.owner.calibration import decision
from app.owner.quality import check_audio, check_speech_duration
from app.speaker.artifacts import IDENTITY
from app.owner.authorization import OperationAuthority, LaunchAuthority
from app.speaker.calibration import waveform_hash
from app.speaker.embedding import cosine
from app.speaker.provenance import binding
from app.commands.basic import resolve_basic
from app.operations.models import Capability as C
from app.launch.models import LaunchPlan, Status
from app.execution.cancellation import GLOBAL

OPERATIONS = frozenset({C.VOLUME_READ, C.VOLUME_UP, C.VOLUME_DOWN, C.VOLUME_SET,
                        C.MUTE, C.UNMUTE, C.BRIGHTNESS_READ, C.STOP, C.CANCEL})
APPLICATIONS = frozenset({"notepad", "calculator", "chrome"})


def resolve(text):
    if type(text) is not str or len(text) > 120:
        raise OwnerError("unsupported_command")
    normalized = text.strip().casefold().rstrip(".?!").strip()
    if normalized in {"open " + app for app in APPLICATIONS}:
        return normalized[5:]
    aliases = {"what is the volume": "read volume", "what is the brightness": "read brightness"}
    try:
        plan = resolve_basic(aliases.get(normalized, normalized))
    except Exception:
        raise OwnerError("unsupported_command") from None
    if plan.capability not in OPERATIONS:
        raise OwnerError("unsupported_command")
    return plan


class Pilot:
    def __init__(self, calibration, operations, launch, *, clock=monotonic, hub=None):
        self.calibration = calibration
        self.settings, self.cfg = calibration.settings, calibration.cfg
        self.operations, self.launch = operations, launch
        self.clock, self.hub = clock, hub or GLOBAL
        self._evidence = {}
        self._seen = set()
        self._admission = None
        self._lock = Lock()
        self.cancel = Event()

    def _take_admission(self, plan, kind):
        row, self._admission = self._admission, None
        if row is None or row[0] is not plan or row[1] != kind:
            raise OwnerError("access_denied")
        row[2]()
        return row[2], self.clock, row[3]

    def preflight(self, profile_id):
        if self.calibration.engine.identity != IDENTITY and not (
            getattr(self.operations.backend, "fake", False) is True
            and getattr(self.launch.backend, "fake", False) is True
        ):
            raise OwnerError("model_mismatch")
        if not self.cfg.pilot_enabled or not self.settings.speaker_verification_enabled:
            raise OwnerError("access_denied")
        if self.cancel.is_set() or self.hub.stopped.is_set():
            raise OwnerError("cancelled")
        return self.calibration.current(profile_id, calibrated=True)

    def authenticate(self, profile_id, session):
        try:
            if type(session) is not UUID or len(self._evidence) >= 32 or len(self._seen) >= 256:
                raise OwnerError()
            profile, record = self.preflight(profile_id)
            score, phrase, digest, capture, _, challenge = self.calibration.measure(
                profile, session, known=(*record.private["digests"], *self._seen))
            self._seen.add(digest)
            outcome = decision(score, record.private["acceptance"], record.private["rejection"])
            if outcome != "accepted":
                return Outcome(status=outcome, reason="speaker_uncertain" if outcome == "retry_or_uncertain" else "speaker_rejected")
            if not phrase:
                raise OwnerError("phrase_mismatch")
            self.preflight(profile_id)
            evidence = Evidence()
            timestamp = self.clock()
            self._evidence[evidence.nonce] = {"profile": profile_id, "provenance": binding(profile),
                "revision": record.private["revision"], "model": profile.model,
                "policy": record.private["policy_version"], "session": session, "challenge": challenge,
                "capture": capture, "phrase_verified": True, "created": timestamp,
                "expires": timestamp + self.cfg.authentication_ttl,
                "inactive": timestamp + self.cfg.inactivity_timeout, "class": "owner-pilot-v1"}
            return Outcome(status="accepted", reason="accepted", evidence=evidence)
        except OwnerError as error:
            return Outcome(status="rejected", reason=error.code)
        except Exception:
            return Outcome(status="rejected", reason="access_denied")

    def check(self, evidence, session, *, consumed=None):
        if type(evidence) is not Evidence:
            raise OwnerError("authentication_replayed")
        row = consumed if consumed is not None else self._evidence.get(evidence.nonce)
        if row is None:
            raise OwnerError("authentication_replayed")
        if self.clock() >= min(row["expires"], row["inactive"]):
            raise OwnerError("authentication_expired")
        if row["session"] != session or not row["phrase_verified"] or row["class"] != "owner-pilot-v1":
            raise OwnerError("binding_mismatch")
        profile, record = self.preflight(row["profile"])
        if (record.private["revision"] != row["revision"] or binding(profile) != row["provenance"]
                or profile.model != row["model"] or record.private["policy_version"] != row["policy"]):
            raise OwnerError("profile_changed")
        return row

    def command(self, evidence, session):
        # Consume on every attempt, including mismatched/expired attempts.
        row = self._evidence.pop(evidence.nonce, None) if type(evidence) is Evidence else None
        if row is None:
            raise OwnerError("authentication_replayed")
        self.check(evidence, session, consumed=row)
        guard = lambda: self.check(evidence, session, consumed=row)
        audio_id = uuid4()
        audio = self.calibration.capture(None, session, audio_id, guard=guard)
        guard()
        profile, record = self.preflight(row["profile"])
        digest = waveform_hash(audio)
        if digest in self._seen or digest in record.private["digests"] or digest in profile.enrollment_hashes:
            raise OwnerError("duplicate_sample")
        self._seen.add(digest)
        check_audio(audio, self.settings.speaker, self.cfg)
        # Authentication of the challenge never implies the next speaker is the owner.
        score = cosine(self.calibration.engine.extract(audio, cancel=self.cancel), profile.template, profile.model.dimension)
        outcome = decision(score, record.private["acceptance"], record.private["rejection"])
        if outcome != "accepted":
            raise OwnerError("speaker_uncertain" if outcome == "retry_or_uncertain" else "speaker_rejected")
        guard()
        if waveform_hash(audio) != digest:
            raise OwnerError("binding_mismatch")
        with timing.span("command_stt"):
            stt = self.calibration.stt.transcribe_audio(audio, audio_id=audio_id, cancel=self.cancel)
        if waveform_hash(audio) != digest:
            raise OwnerError("binding_mismatch")
        if stt.status != "succeeded" or stt.audio_id != audio_id:
            raise OwnerError("stt_rejected")
        check_speech_duration(stt, self.cfg)
        guard()
        with timing.span("planning"):
            plan = resolve(stt.raw_transcript)
        details = {"raw_command": stt.raw_transcript, "normalized_command": stt.normalized_transcript,
                   "canonical_command": plan if type(plan) is str else plan.capability.value,
                   "entities": {"application": plan} if type(plan) is str else {"percentage": plan.percentage}}
        # Freeze command ID/digest in private one-use admission context. No caller can
        # swap in a supplied plan or diagnostic result; plan construction stays here.
        row.update(command_id=audio_id, command_digest=digest)
        observed = {}
        if type(plan) is str:
            observed["application"] = plan
            if not self.settings.launch.real_execution_enabled:
                raise OwnerError("access_denied")
            found = self.launch.backend.discover(plan, self.settings.launch.discovery_timeout)
            if found.status != Status.AVAILABLE or not found.identity:
                raise OwnerError("access_denied")
            guard()
            plan = LaunchPlan(application_id=plan, identity=found.identity,
                              mode="authenticated_voice", authentication_id=evidence.nonce)
            self._admission = (plan, "launch", guard, min(row["expires"], row["inactive"]))
            authority = LaunchAuthority(self, plan)
            result = self.launch.run(plan, authority.permit, authority, cancel=self.cancel)
            success = result.status in {Status.LAUNCHED, Status.ALREADY_RUNNING}
            reason = result.status.value
        else:
            self._admission = (plan, "operations", guard, min(row["expires"], row["inactive"]))
            authority = OperationAuthority(self, plan)
            guard()
            result = self.operations.run(plan, authority.permit, authority, cancel=self.cancel)
            success = result.verified or result.code.value in {"cancel_requested", "nothing_active"}
            reason = result.code.value
            if result.verified and result.volume is not None:
                observed.update(volume_percent=result.volume.percent, muted=result.volume.muted)
            if result.verified and result.brightness is not None:
                observed["brightness_percent"] = result.brightness.percent
        details.update(plan=plan, authorization=authority.permit, execution_result=result)
        return PilotResult(status="completed" if success else "blocked", reason=reason,
                           execution_permitted=result.execution_permitted, details=details, **observed)

    def run(self, profile_id):
        if not self._lock.acquire(blocking=False):
            return PilotResult(status="blocked", reason="access_denied")
        session = uuid4()
        self.calibration.cancel = self.cancel
        try:
            with self.hub.track(self.cancel):
                # Gate before challenge capture and before any model/STT access.
                self.preflight(profile_id)
                result = self.authenticate(profile_id, session)
                if result.status != "accepted":
                    return PilotResult(status="blocked", reason=result.reason)
                return self.command(result.evidence, session)
        except OwnerError as error:
            return PilotResult(status="cancelled" if error.code == "cancelled" else "blocked", reason=error.code)
        except KeyboardInterrupt:
            self.cancel.set()
            return PilotResult(status="cancelled", reason="cancelled")
        except Exception:
            return PilotResult(status="blocked", reason="access_denied")
        finally:
            self._evidence.clear()
            self._admission = None
            self._lock.release()
