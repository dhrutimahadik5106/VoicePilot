import pytest
from app.speaker.evaluate import EvaluationTrial, evaluate, synthetic_demo, sweep, validate_splits

def trial(i,genuine,score,**kw):
    values=dict(trial_id=f"trial_{i}",genuine=genuine,score=score,target="spk_a",
        probe="spk_a" if genuine else "spk_b",enrollment_session="session_enroll",
        probe_session="session_probe",enrollment_recording="rec_enroll",probe_recording=f"rec_probe{i}")
    return EvaluationTrial(**(values|kw))

def test_demo_counts():
    r=synthetic_demo()
    assert (r.true_accept,r.false_reject,r.false_accept,r.true_reject)==(2,2,1,3)
    assert (r.far.numerator,r.far.denominator,r.far.value)==(1,4,.25)
    assert (r.frr.numerator,r.frr.denominator,r.frr.value)==(2,4,.5)
    assert r.uncertain_rate.numerator==2 and r.coverage.value==1
    assert r.eer_estimate==pytest.approx(.5)
    assert "spk_" not in r.model_dump_json()

def test_empty(policy):
    r=evaluate([],policy.configuration)
    assert r.far.value is r.frr.value is r.eer_estimate is None

@pytest.mark.parametrize("genuine_scores,impostor_scores,expected",[
    ([.9,.8],[.1,.2],0),([.1,.2],[.8,.9],1),([.5],[.5],.5),
    ([.9,.5],[.7,.1],.5)])
def test_eer(genuine_scores,impostor_scores,expected):
    trials=[trial(i,True,s) for i,s in enumerate(genuine_scores)]
    trials += [trial(i+10,False,s) for i,s in enumerate(impostor_scores)]
    _,eer=sweep(trials)
    assert eer==pytest.approx(expected)

def test_acquisition_and_denial(policy):
    rows=[trial(1,True,.9),trial(2,True,None,outcome="invalid_audio"),
          trial(3,False,None,outcome="unavailable"),trial(4,True,None,outcome="failure_to_enroll")]
    r=evaluate(rows,policy.configuration)
    assert r.coverage.numerator==1 and r.coverage.denominator==4
    assert r.failure_to_acquire==1 and r.failure_to_enroll==1
    assert r.end_to_end_genuine_denial.numerator==2 and r.end_to_end_genuine_denial.denominator==3

@pytest.mark.parametrize("changes",[
    {"probe_session":"session_enroll"},{"probe_recording":"rec_enroll"}])
def test_enrollment_leakage(changes):
    with pytest.raises(ValueError): validate_splits([trial(1,True,.5,**changes)])

def test_split_leakage():
    with pytest.raises(ValueError): validate_splits([trial(1,True,.5),trial(2,True,.6,cohort="test")])

def test_duplicate():
    row=trial(1,True,.5)
    with pytest.raises(ValueError): validate_splits([row,row])

def test_non_synthetic_policy(policy):
    with pytest.raises(ValueError): evaluate([],policy.configuration.model_copy(update={"calibration":"validated"}))
