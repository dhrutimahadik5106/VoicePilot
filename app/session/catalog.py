"""Metadata only; status never discovers executables or reads a Windows setting."""
from typing import Literal
from app.planning.models import Model
from app.operations.registry import REGISTRY
from app.operations.models import Capability as C
from app.session.models import Risk


class CapabilityView(Model):
    capability_id: str
    implemented: bool
    route: Literal["manual_only","owner_pilot_locked","process_local","unsupported"]
    availability: Literal["not_probed","calibration_blocked","available","unsupported"]
    risk: Risk


def capabilities():
    result = []
    for app in ("notepad","calculator","chrome","spotify"):
        result.append(CapabilityView(capability_id="application.launch." + app, implemented=True,
            route="manual_only" if app == "spotify" else "owner_pilot_locked", availability="not_probed", risk="low"))
    for cap in (C.VOLUME_READ,C.MUTE_READ,C.BRIGHTNESS_READ,C.VOLUME_UP,C.VOLUME_DOWN,C.VOLUME_SET,C.MUTE,C.UNMUTE,C.SCREENSHOT,C.SCREENSHOT_DELETE):
        result.append(CapabilityView(capability_id=cap.value, implemented=True,
            route="manual_only" if cap in {C.SCREENSHOT,C.SCREENSHOT_DELETE} else "owner_pilot_locked",
            availability="not_probed", risk="sensitive" if REGISTRY[cap].risk == "privacy_sensitive" else REGISTRY[cap].risk))
    for cap in ("execution.stop","execution.cancel","execution.emergency_stop"):
        result.append(CapabilityView(capability_id=cap, implemented=True,route="process_local",availability="available",risk="safe"))
    for cap in ("wake_word","global_shortcut","browser.research","screen.perception","input.click",
                "spotify.playback","whatsapp.messaging","files.arbitrary","brightness.mutation","memory.permanent","llm.planning"):
        result.append(CapabilityView(capability_id=cap,implemented=False,route="unsupported",availability="unsupported",risk="unsupported"))
    return tuple(result)
