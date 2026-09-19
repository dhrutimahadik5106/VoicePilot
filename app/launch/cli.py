"""Explicit operator launch consent; inspection never creates a process."""
import argparse
import json
from threading import Event
from uuid import UUID

from app.core.config import Settings
from app.execution.models import State
from app.launch.allowlist import ALLOWLIST, resolve_application
from app.launch.authorization import ManualAuthority, VoiceAuthority
from app.launch.controller import LaunchController
from app.launch.models import LaunchError, LaunchPlan, LaunchResult, Status
from app.launch.windows import WindowsBackend


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise LaunchError(Status.UNSUPPORTED)


def voice_status(settings):
    reason = ("calibration_pending" if settings.speaker.calibration_state != "validated"
              else "production_disabled" if not settings.launch.real_execution_enabled
              else "protected_policy_and_fresh_verification_required")
    return {"mode": "authenticated_voice", "status": "access_denied", "reason": reason,
            "capture": "not_called", "stt": "not_called", "execution_permitted": False}


def main(argv=None, *, settings=None, backend=None, read=input, write=print, recorder=None, pipeline=None):
    parser = Parser(description="Allowlisted Windows launch only; explicit confirmation required")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "status", "authenticated-voice-status"):
        sub.add_parser(name)
    discover = sub.add_parser("discover")
    discover.add_argument("application", nargs="?")
    manual = sub.add_parser("manual-launch-test")
    manual.add_argument("application")
    voice = sub.add_parser("authenticated-voice")
    voice.add_argument("--profile", type=UUID, required=True)
    voice.add_argument("--policy", type=UUID)
    controller = None
    cancel = Event()
    try:
        args = parser.parse_args(argv)
        settings = settings or Settings()
        cfg = settings.launch
        if args.command == "list":
            write(json.dumps({"applications": [entry.model_dump() for entry in ALLOWLIST.values()], "execution_permitted": False}))
            return 0
        if args.command == "status":
            write(json.dumps({"configuration": cfg.model_dump(), "production": voice_status(settings), "execution_permitted": False}))
            return 0
        if args.command == "authenticated-voice-status":
            write(json.dumps(voice_status(settings)))
            return 0
        backend = backend or WindowsBackend()
        if args.command == "discover":
            ids = (resolve_application(args.application),) if args.application else cfg.approved_application_ids
            for app in ids:
                result = backend.discover(app, cfg.discovery_timeout)
                write(result.model_dump_json())
            return 0
        if args.command == "manual-launch-test":
            app = args.application
            if app not in ALLOWLIST or app not in cfg.approved_application_ids:
                raise LaunchError(Status.UNSUPPORTED)
            if not cfg.manual_launch_testing_enabled or not cfg.windows_adapter_enabled:
                raise LaunchError(Status.DISABLED)
            write("MANUAL OPERATOR TEST. This is not voice authentication.")
            write("Proposed application: " + ALLOWLIST[app].display_name + ". One launch; no arguments or elevation.")
            if read("Type the exact application ID " + app + " to continue: ") != app:
                raise LaunchError(Status.CANCELLED)
            discovery = backend.discover(app, cfg.discovery_timeout)
            if discovery.status != Status.AVAILABLE or not discovery.identity:
                raise LaunchError(discovery.status)
            plan = LaunchPlan(application_id=app, identity=discovery.identity)
            authority = ManualAuthority(cfg)
        else:
            if (not cfg.real_execution_enabled or not settings.speaker_verification_enabled
                    or settings.speaker.calibration_state != "validated"):
                write(json.dumps(voice_status(settings)))
                return 2
            if read("Press Enter for one authenticated capture; anything else cancels: ") != "":
                raise LaunchError(Status.CANCELLED)
            if recorder is None:
                from app.audio.recorder import SoundDeviceRecorder
                recorder = SoundDeviceRecorder(settings)
            from app.audio.cli import terminal_control
            captured = recorder.record(min(8, settings.audio_max_duration_seconds), control=terminal_control)
            if captured.status != "succeeded":
                raise LaunchError(Status.CANCELLED)
            authority = VoiceAuthority(settings, backend, pipeline=pipeline)
            plan = authority.prepare(captured.audio, args.profile, policy_id=args.policy, cancel=cancel)
            app = plan.application_id
            write("Authenticated proposal: " + ALLOWLIST[app].display_name + ". One launch; no arguments or elevation.")
        key = authority.challenge(plan, typed_application=app)
        response = read("Type LAUNCH " + app + " to explicitly approve this one application: ")
        permit = authority.confirm(key, plan, response=response)
        controller = LaunchController(cfg, backend=backend)
        result = controller.run(plan, permit, authority, cancel=cancel)
        write(result.model_dump_json())
        return 0 if result.status in {Status.LAUNCHED, Status.ALREADY_RUNNING} else 2
    except (KeyboardInterrupt, EOFError):
        cancel.set()
        if controller is not None:
            controller.emergency_stop()
        write('{"status":"cancelled","execution_permitted":false,"rollback_attempted":false}')
        return 2
    except Exception as error:
        status = error.status if isinstance(error, LaunchError) else Status.LAUNCH_FAILED
        write(json.dumps({"status": status.value, "execution_permitted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
