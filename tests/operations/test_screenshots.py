import json
from threading import Event
from uuid import uuid4
import pytest
from app.execution.cancellation import CancellationHub
from app.operations.capture import encode_header, validate_bmp
from app.operations.screenshots import ScreenshotStore
from app.operations.authorization import ManualAuthority, confirmation
from app.operations.controller import Controller
from app.operations.fakes import FakeBackend
from app.operations.models import Plan, Configuration, Capability as C, Code, OperationError


def fixture(tmp_path):
    cfg=Configuration(enabled=True,screenshot_enabled=True)
    backend=FakeBackend()
    store=ScreenshotStore(root=tmp_path/'screenshots',protector=lambda _:None)
    driver=Controller(cfg,backend=backend,store=store,hub=CancellationHub())
    return driver,backend,store


def authorized(driver,plan):
    authority=ManualAuthority(driver.configuration)
    return driver.run(plan,authority.issue(plan,confirmation(plan)),authority)


def test_capture_save_independently_verify_delete(tmp_path):
    driver,backend,store=fixture(tmp_path)
    result=authorized(driver,Plan(capability=C.SCREENSHOT))
    assert result.code==Code.CAPTURED and result.verified
    assert store.verify(result.artifact_id)==(2,2)
    assert store.path(result.artifact_id).name==str(result.artifact_id)+'.vp-screen.bmp'
    event_text=''.join(e.model_dump_json() for e in driver.history_snapshot())
    assert str(result.artifact_id) not in event_text and str(tmp_path) not in event_text
    deleted=authorized(driver,Plan(capability=C.SCREENSHOT_DELETE,artifact_id=result.artifact_id))
    assert deleted.code==Code.DELETED and not store.exists(result.artifact_id)


@pytest.mark.parametrize('data',[b'',b'PRIVATE_MARKER',encode_header(0,1),encode_header(2,2)+bytes(15),
    b'XX'+encode_header(2,2)[2:]+bytes(16),encode_header(2,2)+bytes(17)])
def test_corrupt_or_empty_capture_not_saved(tmp_path,data):
    driver,backend,store=fixture(tmp_path)
    backend.capture=lambda guard:data
    result=authorized(driver,Plan(capability=C.SCREENSHOT))
    assert not result.verified and not list(tmp_path.rglob('*.bmp'))
    assert 'PRIVATE_MARKER' not in result.model_dump_json()


def test_feature_off_and_missing_confirmation_never_capture(tmp_path):
    driver,backend,store=fixture(tmp_path)
    plan=Plan(capability=C.SCREENSHOT)
    assert not driver.run(plan).verified
    disabled=Controller(Configuration(enabled=True),backend=backend,store=store,hub=CancellationHub())
    assert authorized(disabled,plan).code==Code.DENIED
    assert backend.mutations==0


def test_screenshot_replay_and_expiry(tmp_path):
    driver,backend,store=fixture(tmp_path)
    plan=Plan(capability=C.SCREENSHOT)
    now=[0.0]
    authority=ManualAuthority(driver.configuration,clock=lambda:now[0])
    token=authority.issue(plan,confirmation(plan));now[0]=31
    assert driver.run(plan,token,authority).code==Code.EXPIRED
    token=authority.issue(plan,confirmation(plan))
    assert driver.run(plan,token,authority).verified
    assert driver.run(plan,token,authority).code==Code.REPLAYED
    assert backend.mutations==1


def test_no_overwrite(tmp_path,monkeypatch):
    from app.operations import screenshots
    store=ScreenshotStore(root=tmp_path,protector=lambda _:None)
    key=uuid4();monkeypatch.setattr(screenshots,'uuid4',lambda:key)
    data=encode_header(2,2)+bytes(16)
    assert store.save(data,guard=lambda:None)==key
    with pytest.raises(OperationError):store.save(data,guard=lambda:None)
    assert store.verify(key)==(2,2)


@pytest.mark.parametrize('key',['../private','C:/PRIVATE_MARKER',True,'name.bmp'])
def test_path_injection(tmp_path,key):
    store=ScreenshotStore(root=tmp_path,protector=lambda _:None)
    with pytest.raises(OperationError):store.path(key)


def test_acl_failure_before_private_write(tmp_path):
    def deny(_):raise ValueError('PRIVATE_MARKER')
    store=ScreenshotStore(root=tmp_path,protector=deny)
    with pytest.raises(OperationError) as error:store.save(encode_header(2,2)+bytes(16),guard=lambda:None)
    assert not list(tmp_path.iterdir()) and 'PRIVATE_MARKER' not in str(error.value)


def test_cancel_capture_does_not_save(tmp_path):
    driver,backend,store=fixture(tmp_path)
    backend.after_write=lambda:driver.hub.cancel()
    assert authorized(driver,Plan(capability=C.SCREENSHOT)).code==Code.CANCELLED
    assert not list(tmp_path.rglob('*.bmp'))


def test_false_artifact_observation_never_success(tmp_path):
    driver,backend,store=fixture(tmp_path)
    store.verify=lambda key:False
    result=authorized(driver,Plan(capability=C.SCREENSHOT))
    assert result.code==Code.UNVERIFIED and result.artifact_id is not None
    assert store.exists(result.artifact_id)


def test_selected_corrupt_artifact_can_be_deleted(tmp_path):
    driver,backend,store=fixture(tmp_path)
    result=authorized(driver,Plan(capability=C.SCREENSHOT))
    store.path(result.artifact_id).write_bytes(b'corrupt')
    assert authorized(driver,Plan(capability=C.SCREENSHOT_DELETE,artifact_id=result.artifact_id)).verified


def test_deletion_requires_exact_artifact_consent(tmp_path):
    driver,backend,store=fixture(tmp_path)
    result=authorized(driver,Plan(capability=C.SCREENSHOT))
    plan=Plan(capability=C.SCREENSHOT_DELETE,artifact_id=result.artifact_id)
    assert not driver.run(plan,True,ManualAuthority(driver.configuration)).verified
    assert store.exists(result.artifact_id)
