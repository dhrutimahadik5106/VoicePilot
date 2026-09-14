import pytest
from pydantic import ValidationError
from app.speaker.models import ThresholdConfiguration
from app.speaker.thresholds import BoundedThresholdPolicy
from app.speaker.contracts import SpeakerError

@pytest.mark.parametrize("score,decision",[(-1,"rejected"),(.499999,"rejected"),(.5,"uncertain"),(.799999,"uncertain"),(.8,"verified"),(1,"verified")])
def test_edges(policy,score,decision):
    assert policy.decide(score)==decision

@pytest.mark.parametrize("score",[float("nan"),float("inf"),-1.01,1.01,True])
def test_bad_score(policy,score):
    with pytest.raises(SpeakerError): policy.decide(score)

@pytest.mark.parametrize("accept,review",[(float("nan"),None),(2,None),(.5,.8),(.8,float("inf"))])
def test_bad_policy(identity,accept,review):
    with pytest.raises(ValidationError):
        ThresholdConfiguration(version="test",model=identity,acceptance=accept,review=review)

def test_pending_and_no_band(policy):
    cfg=policy.configuration
    with pytest.raises(SpeakerError):
        BoundedThresholdPolicy(cfg.model_copy(update={"calibration":"pending"})).decide(1.)
    no_band=BoundedThresholdPolicy(cfg.model_copy(update={"review":None}))
    assert no_band.decide(.7)=="rejected"
