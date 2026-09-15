"""Consented private score collection and frozen-policy evaluation; no auto-approval."""
from datetime import datetime, timezone
import hashlib
from typing import Literal
from uuid import UUID, uuid4
from pydantic import Field
from app.speaker.models import SafeModel, ModelIdentity, ThresholdConfiguration
from app.speaker.evaluate import EvaluationTrial, evaluate
from app.speaker.contracts import SpeakerError
from app.speaker.embedding import cosine
from app.speaker.profiles import check_cancel

class ConsentedTrial(SafeModel):
    def __init__(self, **data):
        try:
            super().__init__(**data)
        except Exception:
            raise SpeakerError("invalid_profile") from None

    provenance: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", repr=False, exclude=True)
    record_id: UUID
    target: UUID
    speaker: UUID
    session: UUID
    enrollment_session: UUID
    recording_group: UUID
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$",repr=False,exclude=True)
    enrollment_hashes: tuple[str,...] = Field(repr=False,exclude=True)
    split: Literal["development","validation","test"]
    consent: Literal[True]
    impostor_consent: bool
    model: ModelIdentity
    score: float | None = Field(default=None,ge=-1,le=1,allow_inf_nan=False,repr=False,exclude=True)
    outcome: Literal["scored", "invalid_audio", "unavailable"] = "scored"
    language: Literal["en","hi","mr","mixed"]
    condition: Literal["quiet","noise","other"]
    created_at: str
    def private_document(self):
        return self.model_dump(mode="json") | {"audio_sha256":self.audio_sha256,
            "enrollment_hashes":self.enrollment_hashes,"provenance":self.provenance,"score":self.score,"kind":"trial"}

def waveform_hash(audio):
    digest=hashlib.sha256()
    digest.update(str((audio.format.sample_rate,audio.format.channels)).encode())
    digest.update(audio.samples.tobytes())
    return digest.hexdigest()

def record_trial(audio, profile, engine, store, *, speaker, session, group,
                 split, consent, impostor_consent, language, condition, cancel=None):
    if consent is not True or (speaker != profile.profile_id and impostor_consent is not True):
        raise SpeakerError("consent_required")
    if profile.enrollment_session is None or not profile.enrollment_hashes:
        raise SpeakerError("invalid_profile")
    if session == profile.enrollment_session or engine.identity != profile.model:
        raise SpeakerError("invalid_profile")
    check_cancel(cancel)
    digest=waveform_hash(audio)
    if digest in profile.enrollment_hashes:
        raise SpeakerError("invalid_audio")
    score, outcome = None, "scored"
    try:
        vector=engine.extract(audio,cancel=cancel)
        score=cosine(vector,profile.template,engine.identity.dimension)
    except SpeakerError as error:
        if error.code == "cancelled":
            raise
        outcome="invalid_audio" if error.code in {"invalid_audio","invalid_embedding"} else "unavailable"
    check_cancel(cancel)
    from app.speaker.provenance import binding
    row=ConsentedTrial(provenance=binding(profile),record_id=uuid4(),target=profile.profile_id,speaker=speaker,session=session,
        enrollment_session=profile.enrollment_session,recording_group=group,audio_sha256=digest,
        enrollment_hashes=profile.enrollment_hashes,split=split,consent=True,impostor_consent=impostor_consent,
        model=engine.identity,score=score,outcome=outcome,
        language=language,condition=condition,created_at=datetime.now(timezone.utc).isoformat())
    existing=load_trials(store)
    validate_private_trials([*existing,row])
    store.save(row.record_id,row.private_document(),cancel=cancel)
    return row.record_id

def load_trials(store):
    rows=[]
    for key in store.ids():
        document=store.load(key)
        if document.get("kind") != "trial":
            continue
        document.pop("kind")
        try:
            row=ConsentedTrial.model_validate(document)
            if row.record_id != key:
                raise ValueError()
            rows.append(row)
        except Exception:
            raise SpeakerError("invalid_profile") from None
    return rows

def validate_private_trials(rows):
    seen, maps=set(), {k:{} for k in ("speaker","session","hash","group")}
    all_enrollment={h for r in rows for h in r.enrollment_hashes}
    for r in rows:
        if (r.outcome == "scored") != (r.score is not None):
            raise SpeakerError("invalid_profile")
        if not r.consent or (r.speaker != r.target and not r.impostor_consent):
            raise SpeakerError("consent_required")
        if r.record_id in seen or r.audio_sha256 in all_enrollment or r.session == r.enrollment_session:
            raise SpeakerError("invalid_profile")
        seen.add(r.record_id)
        # Strict research cohorts: same speaker cannot cross splits, including targets.
        for key, values in (("speaker",(r.target,r.speaker)),
                            ("session",(r.session,r.enrollment_session)),
                            ("hash",(r.audio_sha256,)),("group",(r.recording_group,))):
            for value in values:
                if value in maps[key] and maps[key][value] != r.split:
                    raise SpeakerError("invalid_profile")
                maps[key][value]=r.split
    if len({r.audio_sha256 for r in rows}) != len(rows):
        raise SpeakerError("invalid_profile")

def freeze(store, model, acceptance, review, *, consent=False):
    if consent is not True:
        raise SpeakerError("consent_required")
    rows=load_trials(store)
    validate_private_trials(rows)
    selected=[r for r in rows if r.split=="validation" and r.model==model]
    if not selected:
        raise SpeakerError("calibration_pending")
    # A reviewer-chosen operating point is frozen BEFORE test collection/evaluation.
    # Reject freezing after any test data exists, to prevent accidental retuning.
    if any(r.split=="test" for r in rows):
        raise SpeakerError("calibration_pending")
    key=uuid4()
    policy=ThresholdConfiguration(version="frozen-"+key.hex,model=model,
        acceptance=acceptance,review=review,calibration="pending")
    store.save(key,{"kind":"frozen-policy","policy":policy.model_dump(mode="json"),
        "validation_ids":[str(r.record_id) for r in selected],
        "created_at":datetime.now(timezone.utc).isoformat(),
        "authorization_approved":False})
    return key

def evaluate_private(store, frozen_id, split, *, consent=False):
    if consent is not True:
        raise SpeakerError("consent_required")
    rows=load_trials(store)
    validate_private_trials(rows)
    document=store.load(frozen_id)
    if document.get("kind")!="frozen-policy" or document.get("authorization_approved") is not False:
        raise SpeakerError("invalid_profile")
    policy=ThresholdConfiguration.model_validate(document["policy"])
    if policy.calibration!="pending":
        raise SpeakerError("invalid_profile")
    selected=[r for r in rows if r.split==split and
              (split!="validation" or str(r.record_id) in document["validation_ids"])]
    if any(r.model!=policy.model for r in selected):
        raise SpeakerError("incompatible_profile")
    if split=="test" and any(r.created_at<=document["created_at"] for r in selected):
        raise SpeakerError("invalid_profile")
    mapped=[]
    for i,r in enumerate(selected):
        mapped.append(EvaluationTrial(trial_id="trial_"+str(i),genuine=r.speaker==r.target,score=r.score,outcome=r.outcome,
            target="spk_"+r.target.hex,probe="spk_"+r.speaker.hex,
            enrollment_session="session_"+r.enrollment_session.hex,probe_session="session_"+r.session.hex,
            enrollment_recording="rec_"+r.target.hex,probe_recording="rec_"+r.record_id.hex,
            cohort=split))
    # Reuse deterministic numerical formulas, then replace the synthetic label explicitly.
    report=evaluate(mapped,policy.model_copy(update={"calibration":"synthetic"})).model_dump(mode="json")
    report["evidence"]="consented experimental scores; not publication-level biometric accuracy"
    report["calibration"]="pending_review"
    report["authorization_approved"]=False
    report["speakers"]=len({r.speaker for r in selected})
    report["scope"]="personal_development_only" if report["speakers"]<=1 else "consented_experiment"
    report["split"]=split
    report["coverage_scope"]="consented captured trials; cancellations and capture failures before a buffer exists are not retained"
    return report
from app.speaker.models import SpeakerProfile

def approve_frozen(store, repository, frozen_id, profile_id, *, reviewed=False):
    """Explicit operator review with minimum evidence; never automatic enrollment activation.

    20 genuine/20 impostor, 3 impostors and multiple probe sessions are engineering
    eligibility floors, not a statistical security guarantee or publication claim.
    """
    if reviewed is not True:
        raise SpeakerError("consent_required")
    rows=load_trials(store)
    validate_private_trials(rows)
    document=store.load(frozen_id)
    if document.get("kind")!="frozen-policy" or document.get("authorization_approved") is not False:
        raise SpeakerError("invalid_profile")
    policy=ThresholdConfiguration.model_validate(document["policy"])
    selected=[r for r in rows if str(r.record_id) in document["validation_ids"]]
    genuine=[r for r in selected if r.speaker==r.target and r.target==profile_id and r.score is not None]
    impostor=[r for r in selected if r.speaker!=r.target and r.target==profile_id and r.score is not None]
    if (not any(r.score >= policy.acceptance for r in genuine)
            or any(r.score >= policy.acceptance for r in impostor)
            or len({r.recording_group for r in genuine})<20 or len({r.recording_group for r in impostor})<20
            or len(genuine)<20 or len(impostor)<20 or len({r.speaker for r in impostor})<3
            or len({r.session for r in genuine})<2 or len({r.session for r in impostor})<2
            or any(r.split!="validation" or r.model!=policy.model for r in selected)
            or len(selected)!=len(document["validation_ids"])):
        raise SpeakerError("calibration_pending")
    profile=repository.load(profile_id)
    if profile.model!=policy.model or policy.calibration!="pending":
        raise SpeakerError("incompatible_profile")
    from app.speaker.provenance import binding
    current = binding(profile)
    if any(r.target != profile_id or r.enrollment_session != profile.enrollment_session
           or r.enrollment_hashes != profile.enrollment_hashes or r.model != profile.model
           or r.provenance != current for r in selected):
        raise SpeakerError("incompatible_profile")
    key=uuid4()
    approved=policy.model_copy(update={"calibration":"validated","version":"approved-"+key.hex})
    # Policy first: a failed profile replacement leaves an inert orphan policy.
    # Authorization also requires the matching protected profile version.
    changed=SpeakerProfile(**(profile.model_dump()|{"template":profile.template,
        "enrollment_hashes":profile.enrollment_hashes,"calibration":"validated",
        "policy_version":approved.version,"updated_at":datetime.now(timezone.utc)}))
    store.save(key,{"kind":"approved-policy","authorization_approved":True,
        "policy":approved.model_dump(mode="json"),"profiles":[str(profile_id)],
        "provenance":binding(changed),"frozen_reference":str(frozen_id),"reviewed_at":datetime.now(timezone.utc).isoformat()})
    repository.save(changed)
    return key
