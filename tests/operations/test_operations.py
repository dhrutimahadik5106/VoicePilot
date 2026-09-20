import json
from threading import Event
from uuid import uuid4
import pytest
from app.commands.basic import resolve_basic
from app.execution.cancellation import CancellationHub
from app.operations.authorization import ManualAuthority, confirmation
from app.operations.cli import main
from app.operations.controller import Controller
from app.operations.fakes import FakeBackend
from app.operations.models import Capability as C, Code, Configuration, Plan, Result, Volume, OperationError
from app.operations.evaluation import evaluate
from app.operations.adapters import StateAdapter


@pytest.fixture
def setup():
    cfg = Configuration(enabled=True, screenshot_enabled=True)
    backend = FakeBackend()
    hub = CancellationHub()
    return Controller(cfg, backend=backend, hub=hub), backend


def run(driver, cap, percentage=None):
    plan = Plan(capability=cap, percentage=percentage)
    authority = ManualAuthority(driver.configuration)
    return driver.run(plan, authority.issue(plan, confirmation(plan)), authority)


@pytest.mark.parametrize("cap,value,expected", [(C.VOLUME_UP,None,45),(C.VOLUME_DOWN,None,35),
    (C.VOLUME_SET,0,0),(C.VOLUME_SET,100,100),(C.VOLUME_SET,40,40),
    (C.BRIGHTNESS_UP,None,55),(C.BRIGHTNESS_DOWN,None,45),(C.BRIGHTNESS_SET,60,60)])
def test_exact_operation(setup, cap, value, expected):
    driver, backend = setup
    result = run(driver, cap, value)
    assert result.verified and result.fake
    state = result.volume or result.brightness
    assert state.percent == expected
    assert not result.rollback_performed


@pytest.mark.parametrize("start,cap,expected", [(99,C.VOLUME_UP,100),(1,C.VOLUME_DOWN,0),
    (99,C.BRIGHTNESS_UP,100),(1,C.BRIGHTNESS_DOWN,0)])
def test_clamping(setup, start, cap, expected):
    driver, backend = setup
    if cap.value.startswith("system.volume"):
        backend.volume = backend.volume.model_copy(update={"percent": start})
    else:
        backend.brightness = backend.brightness.model_copy(update={"percent": start})
    result = run(driver, cap)
    assert result.verified and (result.volume or result.brightness).percent == expected


@pytest.mark.parametrize("value", [True,False,-1,101,1.0,float("nan"),float("inf"),"40","40 extra",None])
@pytest.mark.parametrize("cap", [C.VOLUME_SET,C.BRIGHTNESS_SET])
def test_invalid_percentages(value, cap):
    with pytest.raises(Exception):
        Plan(capability=cap, percentage=value)


@pytest.mark.parametrize("cap", [C.MUTE,C.UNMUTE])
def test_mute_policy_and_already_correct(setup, cap):
    driver, backend = setup
    result = run(driver, cap)
    assert result.verified and result.volume.muted is (cap==C.MUTE)
    assert result.volume.percent==40
    again=run(driver, cap)
    assert again.code==Code.ALREADY


def test_setting_volume_preserves_mute(setup):
    driver, backend = setup
    backend.volume=backend.volume.model_copy(update={"muted":True})
    result=run(driver,C.VOLUME_SET,70)
    assert result.verified and result.volume.muted is True


@pytest.mark.parametrize("cap", [C.VOLUME_READ,C.MUTE_READ,C.BRIGHTNESS_READ])
def test_reads_need_no_authorization_or_mutation(setup,cap):
    driver,backend=setup
    result=driver.run(Plan(capability=cap))
    assert result.code==Code.READ and result.verified and not backend.mutations


@pytest.mark.parametrize("cap", [C.VOLUME_SET,C.BRIGHTNESS_SET])
def test_false_backend_success(setup,cap):
    driver,backend=setup
    backend.false_success=True
    result=run(driver,cap,80)
    assert result.code==Code.UNVERIFIED and not result.verified and backend.mutations==1
    if cap==C.VOLUME_SET:
        assert result.recovery=="previous_state_observed"


def test_advisory_adapter_cannot_claim_success(setup,monkeypatch):
    driver,backend=setup
    backend.false_success=True
    monkeypatch.setattr(StateAdapter,"verify",lambda *a:True)
    monkeypatch.setattr(StateAdapter,"observe",lambda *a:True)
    assert run(driver,C.VOLUME_SET,80).code==Code.UNVERIFIED


@pytest.mark.parametrize("fault", ["fail_read","fail_write","endpoint","mute_changed","exception","cancel","timeout"])
def test_failure_boundaries(setup,fault):
    driver,backend=setup
    if fault in {"fail_read","fail_write"}:setattr(backend,fault,True)
    elif fault=="endpoint":backend.after_write=lambda:setattr(backend,"volume",backend.volume.model_copy(update={"endpoint":"other"}))
    elif fault=="mute_changed":backend.after_write=lambda:setattr(backend,"volume",backend.volume.model_copy(update={"muted":True}))
    elif fault=="exception":
        def fail():raise ValueError("PRIVATE_MARKER")
        backend.after_write=fail
    elif fault=="cancel":backend.after_write=lambda:driver.hub.cancel()
    else:
        now=[0.0];driver.clock=lambda:now[0]
        backend.after_write=lambda:now.__setitem__(0,10)
    result=run(driver,C.VOLUME_SET,80)
    assert not result.verified and backend.mutations<=1
    assert "PRIVATE_MARKER" not in repr(result)+result.model_dump_json()


@pytest.mark.parametrize("unsupported", ["absent","read_only"])
def test_brightness_unsupported(setup,unsupported):
    driver,backend=setup
    backend.brightness=backend.brightness.model_copy(update={"supported":unsupported!="absent","mutation_supported":False})
    assert run(driver,C.BRIGHTNESS_SET,80).code==Code.UNSUPPORTED
    assert backend.mutations==0


def test_exact_binding_expiry_replay(setup):
    driver,backend=setup
    now=[0.0];authority=ManualAuthority(driver.configuration,clock=lambda:now[0])
    plan=Plan(capability=C.VOLUME_SET,percentage=60)
    token=authority.issue(plan,confirmation(plan))
    assert driver.run(plan.model_copy(update={"percentage":70}),token,authority).code==Code.DENIED
    assert driver.run(plan,token,authority).code==Code.REPLAYED
    token=authority.issue(plan,confirmation(plan));now[0]=31
    assert driver.run(plan,token,authority).code==Code.EXPIRED
    assert backend.mutations==0


@pytest.mark.parametrize("change", [{"action_id":uuid4()},{"version":"other"},{"step_id":"step-2"},
    {"capability":C.BRIGHTNESS_SET},{"percentage":30}])
def test_mutated_plan_never_authorized(setup,change):
    driver,backend=setup
    authority=ManualAuthority(driver.configuration)
    plan=Plan(capability=C.VOLUME_SET,percentage=60)
    token=authority.issue(plan,confirmation(plan))
    assert not driver.run(plan.model_copy(update=change),token,authority).verified
    assert backend.mutations==0


@pytest.mark.parametrize("token", [True,False,None,{"confirmed":True}])
def test_confirmation_bypass_blocked(setup,token):
    driver,backend=setup
    assert not driver.run(Plan(capability=C.MUTE),token,ManualAuthority(driver.configuration)).verified
    assert backend.mutations==0


def test_cancel_global_and_stop_latch(setup):
    driver,backend=setup
    active=Event()
    with driver.hub.track(active):
        assert driver.run(Plan(capability=C.CANCEL)).code==Code.CANCEL_REQUESTED
        assert active.is_set()
    assert driver.run(Plan(capability=C.STOP)).code==Code.NOTHING_ACTIVE
    assert run(driver,C.MUTE).code==Code.STOPPED and backend.mutations==0


def test_history_bounded_private(setup):
    _,backend=setup
    driver=Controller(Configuration(history_limit=2),backend=backend,hub=CancellationHub())
    for _ in range(4):driver.run(Plan(capability=C.VOLUME_READ))
    events=driver.history_snapshot()
    assert len(events)==2
    allowed={"action_id","timestamp","capability","code","duration","fake","confirmation_required","execution_permitted"}
    assert all(set(event.model_dump())==allowed for event in events)
    assert "synthetic-default" not in str(events)


@pytest.mark.parametrize("text", ["Increase volume","Decrease volume","Mute","Unmute","Set volume to 40 percent",
    "Increase brightness","Decrease brightness","Set brightness to 60 percent","Take a screenshot","Stop","Cancel","What did you do?"])
def test_resolver_positive(text):
    assert resolve_basic(text).execution_permitted is False


@pytest.mark.parametrize("text", ["set volume", "set volume to -5 percent", "set volume to 101 percent", "set volume to 40 50 percent",
    "set volume to 40.0 percent","set volume to true percent", "do not mute", "mute and unmute", "stop then screenshot",
    "take a screenshot C:/private", "set brightness to 50 percent and open Chrome", "import os", "system.volume.set 40"])
def test_resolver_rejects_extra_or_ambiguous(text):
    with pytest.raises(OperationError):resolve_basic(text)


def test_defaults_and_diagnostic_cannot_execute(setup):
    driver,backend=setup
    assert not Controller(backend=backend).run(Plan(capability=C.MUTE)).verified
    assert not driver.run({"capability":"system.volume.mute","confirmed":True}).verified
    assert not backend.mutations


def test_evaluation_exact_denominators():
    report=evaluate()["metrics"]
    assert report["valid_operations_verified"]=={"numerator":16,"denominator":16}
    assert report["unsafe_invalid_blocked"]=={"numerator":11,"denominator":11}
    assert report["authorization_bypasses"]=={"numerator":0,"denominator":4}
    assert report["confirmation_bypasses"]=={"numerator":0,"denominator":3}
    assert report["replay_rejection"]=={"numerator":2,"denominator":2}
    assert report["false_successes"]=={"numerator":0,"denominator":26}
    assert report["unsupported_hardware_correct"]=={"numerator":1,"denominator":1}
    assert report["privacy_violations"]=={"numerator":0,"denominator":26}
    assert report["fake_only_enforcement"]=={"numerator":26,"denominator":26}


def test_state_adapter_advisory_verification_checks_full_identity():
    from app.operations.adapters import StateAdapter
    from app.operations.models import Volume, Plan, Capability
    before = Volume(percent=40, muted=True, endpoint="synthetic-default")
    plan = Plan(capability=Capability.VOLUME_SET, percentage=60)
    adapter = StateAdapter(plan.capability, None, before, 60, lambda: None)
    after = Volume(percent=60, muted=True, endpoint="synthetic-default")
    assert adapter.verify(plan, before, after)
    assert not adapter.verify(plan, before, after.model_copy(update={"endpoint": "other"}))
    assert not adapter.verify(plan, before, after.model_copy(update={"muted": False}))


def test_screenshot_adapter_advisory_verification_requires_valid_dimensions():
    from app.operations.adapters import ScreenshotAdapter
    from app.operations.models import Plan, Capability
    plan = Plan(capability=Capability.SCREENSHOT)
    adapter = ScreenshotAdapter(plan.capability, None, None, lambda: None)
    assert adapter.verify(plan, None, (2, 2))
    for dimensions in ((), (0, 2), (True, 2), (16385, 2), (2,), False):
        assert not adapter.verify(plan, None, dimensions)



@pytest.mark.parametrize("fault", ["fail_write", "fail_read", "cancel", "timeout"])
def test_brightness_failure_cancellation_and_timeout(setup, fault):
    driver, backend = setup
    if fault in {"fail_write", "fail_read"}:
        setattr(backend, fault, True)
    elif fault == "cancel":
        backend.after_write = lambda: driver.hub.cancel()
    else:
        now = [0.0]
        driver.clock = lambda: now[0]
        backend.after_write = lambda: now.__setitem__(0, 10)
    result = run(driver, C.BRIGHTNESS_SET, 80)
    assert not result.verified and backend.mutations <= 1
    assert not result.rollback_performed


def test_unknown_capability_and_multiple_actions_rejected():
    for payload in ({"capability": "arbitrary.operation"},
                    {"capability": C.MUTE, "actions": [C.MUTE, C.UNMUTE]}):
        with pytest.raises(Exception):
            Plan.model_validate(payload)
