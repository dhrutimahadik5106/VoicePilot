"""Synthetic development regression counts, not biometric population accuracy."""
from uuid import uuid4
from app.owner.fakes import Harness
from app.owner.models import OwnerError
from app.owner.authorization import OperationAuthority
from app.owner.pilot import resolve


def evaluate():
    totals = {}
    def score(name, positive):
        row = totals.setdefault(name, {"numerator": 0, "denominator": 0})
        row["denominator"] += 1
        row["numerator"] += int(positive)
    for genuine, values in ((True, (.95, .96, .88, .2)), (False, (.2, .3, .88, .95))):
        for value in values:
            harness = Harness().calibrate()
            harness.score = value
            result = harness.pilot.authenticate(harness.profile.profile_id, uuid4())
            prefix = "genuine" if genuine else "impostor"
            for state in ("accepted", "retry_or_uncertain", "rejected"):
                score(prefix + "_" + state, result.status == state)
            score("privacy_violations", any(word in result.model_dump_json() for word in ("similarity", "provenance", "transcript")))
            score("fake_only_enforcement", harness.backend.fake and harness.launch_backend.launched == 0)
    for fault in ("wrong_phrase", "duplicate_capture", "reused_evidence", "expired", "session", "pending"):
        harness = Harness().calibrate()
        session = uuid4()
        if fault == "wrong_phrase": harness.phrase_wrong = True
        if fault == "duplicate_capture": harness.reuse = True
        if fault == "pending": harness.calibration.change(harness.profile.profile_id, "suspend", consent=True)
        result = harness.pilot.authenticate(harness.profile.profile_id, session)
        rejected = result.status != "accepted"
        if not rejected:
            if fault == "expired": harness.now = 100
            try:
                if fault == "reused_evidence":
                    harness.pilot._evidence.clear()
                harness.pilot.command(result.evidence, uuid4() if fault == "session" else session)
            except OwnerError:
                rejected = True
        if fault == "expired": score("expired_evidence_rejection", rejected)
        elif fault != "pending": score("replay_challenge_rejection", rejected)
        score("execution_after_failed_authentication", bool(harness.backend.mutations or harness.launch_backend.launched))
        score("fake_only_enforcement", harness.backend.fake)
        score("privacy_violations", "provenance" in result.model_dump_json())
    for value in (True, {}, object()):
        bypass = False
        try:
            OperationAuthority(value, resolve("mute"))
            bypass = True
        except OwnerError:
            pass
        score("authorization_bypasses", bypass)
    return {"label": "synthetic_development_only_not_population_biometric_accuracy", "metrics": totals}
