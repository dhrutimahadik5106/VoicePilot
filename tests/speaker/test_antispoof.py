from app.speaker.antispoof import UnavailableAntiSpoofing
def test_no_liveness():
    r=UnavailableAntiSpoofing().assess(None)
    assert r.status=="unavailable" and r.assurance=="not_assessed"
