"""Synthetic development safety cases, never hardware or research accuracy claims."""
from app.commands.basic import resolve_basic
from app.execution.cancellation import CancellationHub
from app.operations.authorization import ManualAuthority, confirmation
from app.operations.controller import Controller
from app.operations.fakes import FakeBackend, FakeStore
from threading import Event
from app.operations.models import Capability as C, Plan, Configuration, Code


def evaluate():
    totals = {name: {"numerator": 0, "denominator": 0} for name in (
        "valid_operations_verified", "unsafe_invalid_blocked", "authorization_bypasses",
        "confirmation_bypasses", "replay_rejection", "false_successes",
        "unsupported_hardware_correct", "privacy_violations", "fake_only_enforcement")}
    def score(name, condition):
        totals[name]["denominator"] += 1
        totals[name]["numerator"] += int(condition)
    cfg = Configuration(enabled=True, screenshot_enabled=True)
    expected_volume = {C.VOLUME_READ: (40, False), C.MUTE_READ: (40, False),
        C.VOLUME_UP: (45, False), C.VOLUME_DOWN: (35, False), C.VOLUME_SET: (60, False),
        C.MUTE: (40, True), C.UNMUTE: (40, False)}
    expected_brightness = {C.BRIGHTNESS_READ: 50, C.BRIGHTNESS_UP: 55,
        C.BRIGHTNESS_DOWN: 45, C.BRIGHTNESS_SET: 60}
    for cap in C:
        backend, store, hub = FakeBackend(), FakeStore(), CancellationHub()
        driver = Controller(cfg, backend=backend, store=store, hub=hub)
        key = store.save(backend.capture(lambda: None), guard=lambda: None) if cap == C.SCREENSHOT_DELETE else None
        plan = Plan(capability=cap, percentage=60 if cap in {C.VOLUME_SET, C.BRIGHTNESS_SET} else None,
                    artifact_id=key)
        authority = ManualAuthority(cfg)
        active = Event()
        with hub.track(active):
            result = driver.run(plan, authority.issue(plan, confirmation(plan)), authority)
        if cap in expected_volume:
            observed = (backend.volume.percent, backend.volume.muted) == expected_volume[cap]
        elif cap in expected_brightness:
            observed = backend.brightness.percent == expected_brightness[cap]
        elif cap == C.SCREENSHOT:
            observed = result.artifact_id in store.images and store.verify(result.artifact_id) == (2, 2)
        elif cap == C.SCREENSHOT_DELETE:
            observed = key not in store.images
        elif cap in {C.CANCEL, C.STOP}:
            observed = active.is_set() and (cap != C.STOP or hub.stopped.is_set())
        else:
            observed = len(driver.history_snapshot()) == 1
        success = result.verified or result.code == Code.CANCEL_REQUESTED
        score("valid_operations_verified", success and observed)
        score("false_successes", success and not observed)
        score("fake_only_enforcement", result.fake and type(backend) is FakeBackend)
        score("privacy_violations", "synthetic-default" in str(driver.history_snapshot()))
    for text in ("set volume to -1 percent", "set volume to 101 percent", "set volume to 2.5 percent",
                 "set volume to 40 50 percent", "set volume to percent", "mute and unmute", "do not mute",
                 "take a screenshot C:/private", "powershell", "open adapter", "set brightness to NaN percent"):
        blocked = False
        try:
            resolve_basic(text)
        except Exception:
            blocked = True
        score("unsafe_invalid_blocked", blocked)
    for fault in ("missing", "boolean", "changed", "false_backend", "unsupported", "replay",
                  "screenshot_missing", "screenshot_false", "screenshot_corrupt", "screenshot_replay"):
        backend = FakeBackend()
        store = FakeStore()
        driver = Controller(cfg, backend=backend, store=store, hub=CancellationHub())
        plan = Plan(capability=C.VOLUME_SET, percentage=70)
        authority = ManualAuthority(cfg)
        permit = authority.issue(plan, confirmation(plan))
        if fault.startswith("screenshot_"):
            plan = Plan(capability=C.SCREENSHOT)
            permit = authority.issue(plan, confirmation(plan))
        if fault == "screenshot_missing": permit = None
        if fault == "screenshot_false": store.verify = lambda key: False
        if fault == "screenshot_corrupt": backend.capture = lambda guard: b"invalid"
        if fault == "missing": permit = None
        if fault == "boolean": permit = True
        if fault == "changed": plan = plan.model_copy(update={"percentage": 80})
        if fault == "false_backend": backend.false_success = True
        if fault == "unsupported":
            backend.brightness = backend.brightness.model_copy(update={"supported": False})
            plan = Plan(capability=C.BRIGHTNESS_READ)
        if fault in {"replay", "screenshot_replay"}: driver.run(plan, permit, authority)
        count = backend.mutations
        result = driver.run(plan, permit, authority)
        if fault in {"missing", "boolean", "changed", "screenshot_missing"}:
            score("authorization_bypasses", backend.mutations != count)
        if fault in {"missing", "boolean", "screenshot_missing"}:
            score("confirmation_bypasses", backend.mutations != count)
        if fault in {"replay", "screenshot_replay"}: score("replay_rejection", result.code == Code.REPLAYED and backend.mutations == count)
        if fault == "unsupported": score("unsupported_hardware_correct", result.code == Code.UNSUPPORTED)
        score("false_successes", result.verified)
        score("fake_only_enforcement", result.fake)
        score("privacy_violations", "synthetic-default" in str(driver.history_snapshot()))
    return {"label": "synthetic_development_fakes_only", "metrics": totals}
