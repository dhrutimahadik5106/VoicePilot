"""Explicit operator commands. No voice authorization and no piped confirmation."""
import argparse
import json
import shlex
import sys
from uuid import UUID
from app.core.config import Settings
from app.operations.models import Capability as C, Code, Plan, OperationError
from app.operations.controller import Controller
from app.operations.authorization import ManualAuthority, confirmation
from app.operations.registry import REGISTRY


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OperationError(Code.INVALID)


def percentage(text):
    import re
    if type(text) is not str or re.fullmatch(r"0|[1-9][0-9]?|100", text) is None:
        raise OperationError(Code.INVALID)
    return int(text)


def main(argv=None, *, settings=None, controller=None, read=input, write=print, interactive=None):
    parser = Parser(description="Controlled Windows basic operations; manual tests are not voice authentication")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "volume-status", "mute-status", "brightness-status", "history", "stop", "cancel",
                 "manual-screenshot-test", "authenticated-voice-status", "authenticated-voice", "session", "evaluate"):
        commands.add_parser(name)
    for name in ("manual-volume-test", "manual-brightness-test"):
        child = commands.add_parser(name)
        child.add_argument("action", choices=("increase", "decrease", "set", "mute", "unmute"))
        child.add_argument("percentage", nargs="?", type=percentage)
    child = commands.add_parser("delete-screenshot")
    child.add_argument("artifact_id", type=UUID)
    child = commands.add_parser("plan")
    child.add_argument("text")
    controller_instance = controller
    try:
        args = parser.parse_args(argv)
        settings = settings or Settings()
        cfg = settings.operations
        tty = (lambda: sys.stdin.isatty() and sys.stdout.isatty()) if interactive is None else interactive
        if args.command in {"authenticated-voice", "authenticated-voice-status"}:
            write(json.dumps({"status": "access_denied", "reason": "calibration_pending" if settings.speaker.calibration_state != "validated" else "production_issuer_unavailable",
                              "capture": "not_called", "stt": "not_called", "execution_permitted": False}))
            return 2 if args.command == "authenticated-voice" else 0
        if args.command == "status":
            write(json.dumps({"configuration": cfg.model_dump(), "brightness_mutation": "unsupported",
                "screenshot_target": "primary_display", "history": "process_local_only", "execution_permitted": False}))
            return 0
        if args.command == "evaluate":
            from app.operations.evaluation import evaluate
            write(json.dumps(evaluate()))
            return 0
        if args.command == "plan":
            from app.commands.basic import resolve_basic
            plan = resolve_basic(args.text)
            write(json.dumps(plan.model_dump(mode="json") | {"risk": REGISTRY[plan.capability].risk,
                "confirmation_required": REGISTRY[plan.capability].mutation}))
            return 0
        controller_instance = controller_instance or Controller(cfg)
        if args.command == "session":
            if not tty():
                raise OperationError(Code.DENIED)
            write("MANUAL OPERATOR SESSION. Not voice authentication. History ends with this process. Type exit to finish.")
            for _ in range(100):
                line = read("operation> ")
                if line == "exit":
                    return 0
                parts = shlex.split(line)
                if not parts or parts[0] == "session":
                    write('{"code":"invalid_argument"}')
                    continue
                main(parts, settings=settings, controller=controller_instance, read=read, write=write, interactive=tty)
            return 0
        mapping = {"volume-status": C.VOLUME_READ, "mute-status": C.MUTE_READ, "brightness-status": C.BRIGHTNESS_READ,
                   "history": C.HISTORY, "stop": C.STOP, "cancel": C.CANCEL, "manual-screenshot-test": C.SCREENSHOT,
                   "delete-screenshot": C.SCREENSHOT_DELETE}
        if args.command in mapping:
            plan = Plan(capability=mapping[args.command], artifact_id=getattr(args, "artifact_id", None))
        else:
            group = "volume" if args.command == "manual-volume-test" else "brightness"
            cap = C("system." + group + "." + args.action)
            plan = Plan(capability=cap, percentage=args.percentage)
        if plan.capability == C.HISTORY:
            write(json.dumps({"history": [event.model_dump(mode="json") for event in controller_instance.history_snapshot()],
                              "execution_permitted": False}))
            return 0
        permit = authority = None
        if REGISTRY[plan.capability].mutation:
            if not cfg.enabled or not cfg.manual_testing_enabled or not tty():
                raise OperationError(Code.DENIED)
            if plan.capability == C.SCREENSHOT and not cfg.screenshot_enabled:
                raise OperationError(Code.DENIED)
            write("MANUAL OPERATOR TEST. This is not voice authentication.")
            write("Proposed effect: " + plan.capability.value + (" " + str(plan.percentage) + " percent" if plan.percentage is not None else ""))
            if plan.capability == C.SCREENSHOT:
                write("Privacy warning: the primary-display screenshot may contain private information. Confirmation approves capture AND local saving.")
            authority = ManualAuthority(cfg)
            response = read("Type exactly " + confirmation(plan) + ": ")
            permit = authority.issue(plan, response)
        result = controller_instance.run(plan, permit, authority)
        write(result.model_dump_json())
        return 0 if result.verified or result.code in {Code.CANCEL_REQUESTED, Code.NOTHING_ACTIVE} else 2
    except (KeyboardInterrupt, EOFError):
        if controller_instance is not None:
            controller_instance.hub.cancel()
        write('{"code":"cancelled","execution_permitted":false}')
        return 2
    except Exception as error:
        code = error.code if isinstance(error, OperationError) else Code.INVALID
        write(json.dumps({"code": code.value, "execution_permitted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
