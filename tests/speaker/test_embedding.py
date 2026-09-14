import numpy as np
import pytest
from app.speaker.embedding import normalized, cosine, UnavailableEmbeddingEngine
from app.speaker.contracts import SpeakerError

@pytest.mark.parametrize("vector", [[], [1,2], [[1,2,3]], [0,0,0], [1,float("nan"),0],
    [float("inf"),0,0], ["PRIVATE",0,0], object()])
def test_invalid_vectors(vector):
    with pytest.raises(SpeakerError, match="^invalid_embedding$") as error:
        normalized(vector,3)
    assert "PRIVATE" not in str(error.value)

@pytest.mark.parametrize("vector", [[3.,4.,0.],[1e308,1e308,0],[1e-300,0,0],[-1,0,0]])
def test_normalized(vector):
    result=normalized(vector,3)
    assert np.isfinite(result).all()
    assert np.linalg.norm(result)==pytest.approx(1)

@pytest.mark.parametrize("vector,score", [([1,0,0],1),([-1,0,0],-1),([0,1,0],0)])
def test_cosine(vector,score):
    assert cosine([1,0,0],vector,3)==pytest.approx(score)

def test_unavailable():
    with pytest.raises(SpeakerError,match="unavailable"): UnavailableEmbeddingEngine().extract(None)
