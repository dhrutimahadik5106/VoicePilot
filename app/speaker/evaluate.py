"""Deterministic synthetic scores, never biometric performance evidence."""
from typing import Literal
from pydantic import Field, model_validator
from app.speaker.models import SafeModel
from app.speaker.thresholds import BoundedThresholdPolicy

class EvaluationTrial(SafeModel):
    trial_id: str = Field(pattern=r"^trial_[a-z0-9]{1,32}$")
    genuine: bool
    score: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    outcome: Literal["scored", "invalid_audio", "invalid_profile", "unavailable", "cancelled", "failure_to_enroll"] = "scored"
    cohort: Literal["development", "validation", "test"] = "development"
    target: str = Field(pattern=r"^spk_[a-z0-9]{1,32}$", repr=False, exclude=True)
    probe: str = Field(pattern=r"^spk_[a-z0-9]{1,32}$", repr=False, exclude=True)
    enrollment_session: str = Field(pattern=r"^session_[a-z0-9]{1,32}$", repr=False, exclude=True)
    probe_session: str = Field(pattern=r"^session_[a-z0-9]{1,32}$", repr=False, exclude=True)
    enrollment_recording: str = Field(pattern=r"^rec_[a-z0-9]{1,32}$", repr=False, exclude=True)
    probe_recording: str = Field(pattern=r"^rec_[a-z0-9]{1,32}$", repr=False, exclude=True)
    @model_validator(mode="after")
    def consistent(self):
        if (self.genuine != (self.target == self.probe)
                or (self.outcome == "scored") != (self.score is not None)):
            raise ValueError("invalid_trial")
        return self

class Rate(SafeModel):
    numerator: int
    denominator: int
    value: float | None

def rate(numerator, denominator):
    return Rate(numerator=numerator, denominator=denominator,
                value=numerator / denominator if denominator else None)

class EvaluationReport(SafeModel):
    evidence: Literal["synthetic development evidence - not real biometric performance"] = "synthetic development evidence - not real biometric performance"
    total: int
    scored: int
    true_accept: int
    true_reject: int
    false_accept: int
    false_reject: int
    far: Rate
    frr: Rate
    genuine_acceptance: Rate
    impostor_rejection: Rate
    uncertain_rate: Rate
    coverage: Rate
    decisive_coverage: Rate
    end_to_end_genuine_denial: Rate
    failure_to_enroll: int
    failure_to_acquire: int
    outcomes: dict[str, int]
    eer_estimate: float | None
    eer_method: Literal["linear_interpolation_adjacent_empirical_points"] = "linear_interpolation_adjacent_empirical_points"
    threshold_curve: tuple[dict[str, float | None], ...]

def validate_splits(trials):
    seen, owners, recording_owners, roles = set(), {}, {}, {}
    for t in trials:
        if t.trial_id in seen:
            raise ValueError("duplicate_trial")
        seen.add(t.trial_id)
        if t.enrollment_session == t.probe_session or t.enrollment_recording == t.probe_recording:
            raise ValueError("enrollment_probe_leakage")
        for speaker in (t.target, t.probe):
            if speaker in owners and owners[speaker] != t.cohort:
                raise ValueError("speaker_split_leakage")
            owners[speaker] = t.cohort
        for recording, speaker, session, role in (
                (t.enrollment_recording, t.target, t.enrollment_session, "enrollment"),
                (t.probe_recording, t.probe, t.probe_session, "probe")):
            identity = (speaker, session, t.cohort)
            if recording in recording_owners and recording_owners[recording] != identity:
                raise ValueError("recording_split_leakage")
            if recording in roles and roles[recording] != role:
                raise ValueError("recording_role_leakage")
            recording_owners[recording], roles[recording] = identity, role
        # Session identifiers must be cohort-local even when different speakers share a session.
        for session in (t.enrollment_session, t.probe_session):
            key = ("session", session)
            if key in owners and owners[key] != t.cohort:
                raise ValueError("session_split_leakage")
            owners[key] = t.cohort

def sweep(trials):
    scored = [t for t in trials if t.score is not None]
    genuine = [t.score for t in scored if t.genuine]
    impostor = [t.score for t in scored if not t.genuine]
    if not genuine or not impostor:
        return (), None
    # None is the conceptual reject-all endpoint above the maximum score.
    thresholds = [None, *sorted({t.score for t in scored}, reverse=True)]
    curve = []
    for threshold in thresholds:
        far = sum(s >= threshold for s in impostor) / len(impostor) if threshold is not None else 0.
        frr = sum(s < threshold for s in genuine) / len(genuine) if threshold is not None else 1.
        curve.append({"threshold":threshold, "far":far, "frr":frr})
    eer = None
    for a, b in zip(curve, curve[1:]):
        da, db = a["far"]-a["frr"], b["far"]-b["frr"]
        if da == 0:
            eer = a["far"]
            break
        if da <= 0 <= db:
            fraction = -da / (db-da)
            eer = a["far"] + fraction * (b["far"]-a["far"])
            break
    return tuple(curve), eer

def evaluate(trials, configuration):
    trials = tuple(trials)
    validate_splits(trials)
    if configuration.calibration != "synthetic":
        raise ValueError("synthetic_policy_required")
    policy = BoundedThresholdPolicy(configuration)
    counts = dict(TA=0, TR=0, FA=0, FR=0)
    uncertain = 0
    outcomes = {}
    for t in trials:
        outcomes[t.outcome] = outcomes.get(t.outcome, 0) + 1
        if t.score is None:
            continue
        decision = policy.decide(t.score)
        accepted = decision == "verified"
        uncertain += decision == "uncertain"
        key = ("TA" if accepted else "FR") if t.genuine else ("FA" if accepted else "TR")
        counts[key] += 1
    ta, tr, fa, fr = (counts[k] for k in ("TA", "TR", "FA", "FR"))
    ng, ni = ta+fr, tr+fa
    scored, total = ng+ni, len(trials)
    genuine_attempts = sum(t.genuine for t in trials)
    curve, eer = sweep(trials)
    return EvaluationReport(total=total, scored=scored, true_accept=ta, true_reject=tr,
        false_accept=fa, false_reject=fr, far=rate(fa, ni), frr=rate(fr, ng),
        genuine_acceptance=rate(ta, ng), impostor_rejection=rate(tr, ni),
        uncertain_rate=rate(uncertain, scored), coverage=rate(scored, total),
        decisive_coverage=rate(scored-uncertain, total),
        end_to_end_genuine_denial=rate(genuine_attempts-ta, genuine_attempts),
        failure_to_enroll=outcomes.get("failure_to_enroll", 0),
        failure_to_acquire=outcomes.get("invalid_audio", 0),
        outcomes=outcomes, eer_estimate=eer, threshold_curve=curve)

def synthetic_demo():
    from app.speaker.models import ModelIdentity, ThresholdConfiguration
    model = ModelIdentity(name="synthetic", revision="v1", sha256="0"*64, preprocessing="synthetic-v1", dimension=3)
    cfg = ThresholdConfiguration(version="synthetic-v1", model=model, acceptance=.8, review=.5, calibration="synthetic")
    trials = []
    for i, (genuine, score) in enumerate(((True,.95),(True,.85),(True,.6),(True,.2),
                                        (False,.9),(False,.65),(False,.3),(False,-.2))):
        trials.append(EvaluationTrial(trial_id=f"trial_{i}", genuine=genuine, score=score,
            target="spk_a", probe="spk_a" if genuine else "spk_b",
            enrollment_session="session_enroll", probe_session="session_probe",
            enrollment_recording="rec_enroll", probe_recording=f"rec_probe{i}"))
    return evaluate(trials, cfg)
