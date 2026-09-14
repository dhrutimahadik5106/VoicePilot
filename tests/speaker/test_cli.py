import json
import pytest
from app.speaker.cli import main

@pytest.mark.parametrize("args,code",[
    (["inspect-status"],0),(["inspect-policy"],0),(["validate-schema"],0),
    (["evaluate","--synthetic"],0),(["profiles","list"],2),(["enroll"],2),(["verify"],2),
    (["PRIVATE_ARGUMENT"],2)])
def test_safe_cli(args,code):
    output=[]
    assert main(args,write=output.append)==code
    value=json.loads(output[0])
    assert "PRIVATE_ARGUMENT" not in output[0]
    assert "template" not in output[0] and "C:\\" not in output[0]
    assert value

def test_cli_no_profile_access(monkeypatch):
    from app.speaker.profiles import ProtectedProfileRepository
    def fail(*a,**kw): raise AssertionError("filesystem_access")
    monkeypatch.setattr(ProtectedProfileRepository,"list_ids",fail)
    output=[]
    assert main(["profiles","list"],write=output.append)==2
    assert json.loads(output[0])["status"]=="unavailable"
