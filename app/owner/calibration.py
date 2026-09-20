"""Owner-only calibration protocol. No template migration and no raw persistence."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4
from app.owner.models import Record, State, OwnerError
from app.owner.challenge import Challenges, PHRASES
from app.owner.quality import check_audio, check_speech_duration
from app.speaker.provenance import binding
from app.speaker.calibration import waveform_hash
from app.speaker.embedding import cosine
from app.speaker.profiles import check_cancel
from app.speaker.contracts import SpeakerError


def now():
    return datetime.now(timezone.utc).isoformat()


def policy_binding(settings):
    # Includes quality and engineering floors, so editing settings cannot reuse approval.
    return sha256(json.dumps({"owner": settings.owner.model_dump(exclude={"calibration_enabled", "pilot_enabled"}),
        "speaker": settings.speaker.model_dump()}, sort_keys=True, default=str).encode()).hexdigest()


def decision(score, acceptance, rejection):
    return "accepted" if score >= acceptance else "retry_or_uncertain" if score >= rejection else "rejected"


def aggregate():
    return {"count": 0, "minimum": 1., "maximum": -1., "sum": 0.,
            "accepted": 0, "retry_or_uncertain": 0, "rejected": 0}


class Calibration:
    def __init__(self, settings, repository, store, engine, stt, capture, *, challenges=None, cancel=None):
        self.settings, self.cfg = settings, settings.owner
        self.repository, self.store, self.engine = repository, store, engine
        self.stt, self.capture, self.cancel = stt, capture, cancel
        self.challenges = challenges or Challenges(self.cfg)

    def profile(self, profile_id):
        try:
            profile = self.repository.load(profile_id)
            binding(profile)
            if profile.profile_id != profile_id or profile.model != self.engine.identity:
                raise OwnerError("model_mismatch")
            return profile
        except OwnerError:
            raise
        except Exception:
            raise OwnerError("profile_missing") from None

    def current(self, profile_id, *, calibrated=False):
        profile = self.profile(profile_id)
        record = self.store.load(profile_id)
        data = record.private
        try:
            if data["provenance"] != binding(profile) or data["model"] != profile.model.model_dump(mode="json"):
                raise OwnerError("profile_changed")
            if data["configuration"] != policy_binding(self.settings):
                raise OwnerError("calibration_required")
            UUID(data["revision"])
            if calibrated and record.state != State.CALIBRATED:
                raise OwnerError("calibration_required")
            if calibrated and not self.eligible(data):
                raise OwnerError("calibration_inconclusive")
        except OwnerError:
            raise
        except Exception:
            raise OwnerError("profile_corrupt") from None
        return profile, record

    def begin(self, profile_id, *, consent=False):
        if not self.cfg.calibration_enabled or consent is not True:
            raise OwnerError("consent_required")
        profile = self.profile(profile_id)
        previous = None
        try:
            existing = self.store.load(profile_id)
            if existing.state not in {State.REVOKED, State.FAILED, State.INCONCLUSIVE}:
                raise OwnerError("invalid_transition")
            previous = existing.private["revision"]
        except OwnerError as error:
            if error.code != "calibration_required":
                raise
        data = {"profile": str(profile_id), "provenance": binding(profile),
                "model": profile.model.model_dump(mode="json"), "configuration": policy_binding(self.settings),
                "revision": str(uuid4()), "policy_version": "owner-policy-v1", "consent": str(uuid4()),
                "created_at": now(), "updated_at": now(), "owner": aggregate(), "holdout": aggregate(),
                "nonowner": aggregate(), "replay": {"count": 0, "rejected": 0},
                "owner_groups": [], "owner_phrases": [], "nonowner_speakers": [],
                "nonowner_groups": [], "holdout_groups": [], "digests": [], "captures": [],
                "sessions": [], "acceptance": None, "rejection": None, "frozen_at": None}
        self.store.save(profile_id, Record(private=data), previous=previous)
        return self.status(profile_id)

    def save(self, profile_id, record, data, state):
        check_cancel(self.cancel)
        # Re-read immediately before every commit; stale enrollment evidence cannot be appended.
        self.current(profile_id)
        data["revision"], data["updated_at"] = str(uuid4()), now()
        self.store.save(profile_id, Record(state=state, private=data), previous=record.private["revision"])

    def measure(self, profile, session, *, wrong_phrase=False, known=()):
        check_cancel(self.cancel)
        challenge = self.challenges.create(session)
        expires = self.challenges.pending[challenge.handle][2]
        prompt = PHRASES[(PHRASES.index(challenge.phrase) + 1) % len(PHRASES)] if wrong_phrase else challenge.phrase
        audio_id = uuid4()
        def capture_guard():
            check_cancel(self.cancel)
            if self.challenges.clock() >= expires:
                raise OwnerError("challenge_expired")
        try:
            audio = self.capture(prompt, session, audio_id, guard=capture_guard)
            expected = self.challenges.consume(challenge, session)
            check_cancel(self.cancel)
            check_audio(audio, self.settings.speaker, self.cfg)
            digest = waveform_hash(audio)
            if digest in profile.enrollment_hashes or digest in known:
                raise OwnerError("duplicate_sample")
            vector = self.engine.extract(audio, cancel=self.cancel)
            score = cosine(vector, profile.template, profile.model.dimension)
            del vector
            check_cancel(self.cancel)
            if waveform_hash(audio) != digest:
                raise OwnerError("binding_mismatch")
            transcript = self.stt.transcribe_audio(audio, audio_id=audio_id, cancel=self.cancel)
            if waveform_hash(audio) != digest:
                raise OwnerError("binding_mismatch")
            if transcript.status != "succeeded" or transcript.audio_id != audio_id:
                raise OwnerError("stt_rejected")
            check_speech_duration(transcript, self.cfg)
            phrase_ok = True
            try:
                # Raw concatenation can fuse adjacent segments. Use the shared STT
                # boundary-whitespace view, never refinement or guessed word splits.
                self.challenges.verify(expected, transcript.normalized_transcript)
            except OwnerError:
                phrase_ok = False
            if self.challenges.clock() >= expires:
                raise OwnerError("challenge_expired")
            check_cancel(self.cancel)
            return score, phrase_ok, digest, str(audio_id), PHRASES.index(expected), challenge.handle
        except OwnerError:
            raise
        except SpeakerError as error:
            code = "cancelled" if error.code == "cancelled" else "capture_quality_failed" if error.code in {"invalid_audio", "invalid_embedding"} else "access_denied"
            raise OwnerError(code) from None
        except Exception:
            raise OwnerError("access_denied") from None
        finally:
            self.challenges.pending.pop(challenge.handle, None)

    def collect(self, profile_id, group, environment, *, consent=False, participant=None):
        if not self.cfg.calibration_enabled or consent is not True:
            raise OwnerError("consent_required")
        if environment not in {"quiet", "different_environment"} or group not in {"owner", "holdout", "nonowner", "replay"}:
            raise OwnerError()
        profile, record = self.current(profile_id)
        allowed = {"owner": {State.OWNER, State.OWNER_COMPLETE},
                   "nonowner": {State.OWNER_COMPLETE, State.NONOWNER},
                   "holdout": {State.HOLDOUT}, "replay": {State.REPLAY}}
        if record.state not in allowed[group]:
            raise OwnerError("invalid_transition")
        if group == "nonowner" and (type(participant) is not UUID or participant == profile_id):
            raise OwnerError("consent_required")
        data = deepcopy(record.private)
        if len(data["digests"]) >= 128:
            raise OwnerError("insufficient_samples")
        session = uuid4()
        if session == profile.enrollment_session:
            raise OwnerError("binding_mismatch")
        score, phrase_ok, digest, capture, phrase, _ = self.measure(profile, session,
            wrong_phrase=group == "replay", known=data["digests"])
        # Rejected acquisitions never enter distributions. Replay requires a genuine
        # owner match but the WRONG fresh phrase: it tests the challenge gate, not liveness.
        if group == "replay":
            if phrase_ok or decision(score, data["acceptance"], data["rejection"]) != "accepted":
                data["replay"]["count"] += 1
                self.save(profile_id, record, data, State.FAILED)
                return self.status(profile_id)
            data["replay"]["count"] += 1
            data["replay"]["rejected"] += 1
            state = State.REPLAY
        else:
            if not phrase_ok:
                raise OwnerError("phrase_mismatch")
            stats = data[group]
            stats["count"] += 1
            stats["minimum"] = min(stats["minimum"], score)
            stats["maximum"] = max(stats["maximum"], score)
            stats["sum"] += score
            if group == "holdout":
                stats[decision(score, data["acceptance"], data["rejection"])] += 1
            groups = data[group + "_groups"]
            if environment not in groups:
                groups.append(environment)
            if group == "owner":
                if phrase not in data["owner_phrases"]:
                    data["owner_phrases"].append(phrase)
                state = State.OWNER_COMPLETE if stats["count"] >= self.cfg.minimum_owner_samples else State.OWNER
            elif group == "nonowner":
                if str(participant) not in data["nonowner_speakers"]:
                    data["nonowner_speakers"].append(str(participant))
                state = State.NONOWNER
            else:
                state = State.REPLAY if stats["count"] >= self.cfg.minimum_holdout_samples else State.HOLDOUT
        data["digests"].append(digest)
        data["captures"].append(capture)
        data["sessions"].append(str(session))
        self.save(profile_id, record, data, state)
        return self.status(profile_id)

    def freeze(self, profile_id):
        if not self.cfg.calibration_enabled:
            raise OwnerError("access_denied")
        _, record = self.current(profile_id)
        if record.state != State.NONOWNER:
            raise OwnerError("invalid_transition")
        data = deepcopy(record.private)
        if (data["owner"]["count"] < self.cfg.minimum_owner_samples or len(data["owner_groups"]) < 2
                or len(data["owner_phrases"]) < 3 or data["nonowner"]["count"] < self.cfg.minimum_nonowner_samples
                or len(data["nonowner_speakers"]) < self.cfg.minimum_nonowner_speakers
                or len(data["nonowner_groups"]) < 2):
            raise OwnerError("insufficient_samples")
        acceptance = max(self.cfg.acceptance_floor, self.cfg.rejection_floor + self.cfg.uncertainty_band,
                         data["owner"]["minimum"] - .02,
                         data["nonowner"]["maximum"] + self.cfg.uncertainty_band + .02)
        rejection = acceptance - self.cfg.uncertainty_band
        if acceptance > 1 or data["owner"]["minimum"] < acceptance or data["nonowner"]["maximum"] >= rejection:
            self.save(profile_id, record, data, State.INCONCLUSIVE)
            return self.status(profile_id)
        data.update(acceptance=acceptance, rejection=rejection, frozen_at=now())
        # All development owners accepted and all non-owners rejected at this point;
        # holdouts are collected later and never used to tune these boundaries.
        data["owner"]["accepted"] = data["owner"]["count"]
        data["nonowner"]["rejected"] = data["nonowner"]["count"]
        self.save(profile_id, record, data, State.HOLDOUT)
        return self.status(profile_id)

    def eligible(self, data):
        return (data["owner"]["count"] >= self.cfg.minimum_owner_samples
                and len(data["owner_groups"]) >= 2 and len(data["owner_phrases"]) >= 3
                and data["nonowner"]["count"] >= self.cfg.minimum_nonowner_samples
                and len(data["nonowner_speakers"]) >= self.cfg.minimum_nonowner_speakers
                and len(data["nonowner_groups"]) >= 2
                and data["holdout"]["count"] >= self.cfg.minimum_holdout_samples
                and len(data["holdout_groups"]) >= 2
                and data["holdout"]["accepted"] == data["holdout"]["count"]
                and data["replay"]["count"] >= self.cfg.minimum_replay_trials
                and data["replay"]["rejected"] == data["replay"]["count"]
                and data["rejection"] >= self.cfg.rejection_floor - 1e-9
                and data["acceptance"] >= self.cfg.acceptance_floor
                and data["acceptance"] - data["rejection"] >= self.cfg.uncertainty_band - 1e-9
                and data["nonowner"]["maximum"] < data["rejection"]
                and data["owner"]["minimum"] >= data["acceptance"])

    def evaluate(self, profile_id):
        if not self.cfg.calibration_enabled:
            raise OwnerError("access_denied")
        _, record = self.current(profile_id)
        if record.state not in {State.REPLAY, State.SUSPENDED, State.EVALUATING}:
            raise OwnerError("invalid_transition")
        state = State.EVALUATING if self.eligible(record.private) else State.INCONCLUSIVE
        self.save(profile_id, record, deepcopy(record.private), state)
        return self.status(profile_id)

    def approve(self, profile_id, *, consent=False):
        if not self.cfg.calibration_enabled:
            raise OwnerError("access_denied")
        _, record = self.current(profile_id)
        if consent is not True:
            raise OwnerError("consent_required")
        if record.state != State.EVALUATING or not self.eligible(record.private):
            raise OwnerError("calibration_inconclusive")
        self.save(profile_id, record, deepcopy(record.private), State.CALIBRATED)
        return self.status(profile_id)

    def change(self, profile_id, action, *, consent=False):
        if consent is not True:
            raise OwnerError("consent_required")
        # Revocation must remain possible even if provenance or settings changed.
        try:
            record = self.store.load(profile_id)
        except OwnerError as error:
            if action != "delete" or error.code not in {"calibration_required", "profile_corrupt"}:
                raise
            # Removing the nominated profile invalidates all evidence even when its
            # owner summary is absent/corrupt. No other private files are touched.
            self.repository.delete(profile_id)
            self.store.delete(profile_id)
            return {"state": "deleted"}
        if action == "suspend" and record.state != State.CALIBRATED:
            raise OwnerError("invalid_transition")
        if action not in {"suspend", "revoke", "delete"}:
            raise OwnerError("invalid_transition")
        data = deepcopy(record.private)
        data["revision"], data["updated_at"] = str(uuid4()), now()
        self.store.save(profile_id, Record(state=State.SUSPENDED if action == "suspend" else State.REVOKED,
                        private=data), previous=record.private["revision"])
        if action == "delete":
            self.repository.delete(profile_id)
            self.store.delete(profile_id)
        return {"state": "deleted" if action == "delete" else "suspended" if action == "suspend" else "revoked"}

    def status(self, profile_id):
        try:
            _, record = self.current(profile_id)
        except OwnerError as error:
            if error.code in {"profile_missing", "calibration_required"}:
                return {"state": "not_enrolled" if error.code == "profile_missing" else "enrolled_uncalibrated",
                        "raw_audio_saved": False}
            raise
        data = record.private
        return {"state": record.state.value, "owner_count": data["owner"]["count"],
                "nonowner_count": data["nonowner"]["count"], "holdout_count": data["holdout"]["count"],
                "owner_outcomes": {k: data["owner"][k] for k in ("accepted", "retry_or_uncertain", "rejected")},
                "nonowner_outcomes": {k: data["nonowner"][k] for k in ("accepted", "retry_or_uncertain", "rejected")},
                "holdout_outcomes": {k: data["holdout"][k] for k in ("accepted", "retry_or_uncertain", "rejected")},
                "replay": data["replay"], "raw_audio_saved": False,
                "scope": "small_personal_evaluation_not_population_accuracy"}
