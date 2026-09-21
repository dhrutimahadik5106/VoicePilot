"""Explicit terminal calibration and authenticated pilot. No automatic recording."""
import argparse
import json
import sys
from uuid import UUID
from app.core import timing
from app.core.config import Settings
from app.owner.models import OwnerError, TrialConsent

PRIVACY = ("Owner calibration collects fresh prompted microphone samples and temporary speaker embeddings. "
    "No raw audio or transcripts are saved. Only encrypted calibration aggregates, consent IDs and "
    "provenance/reuse identifiers persist under LocalAppData/VoicePilot/owner-calibration; existing "
    "encrypted profiles stay under their approved private profile directory. Non-owner embeddings are discarded. "
    "Each non-owner must personally consent. Every recording requires Enter; other input or Ctrl+C cancels. "
    "Use revoke or delete with exact confirmation. No calibration command executes Windows actions. "
    "Random public phrases are not strong liveness or protection against cloning/injection.")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OwnerError()


def main(argv=None, *, settings=None, factory=None, read=input, write=print, interactive=None):
    timing_report = timing_token = None
    try:
        parser = Parser(description="Owner calibration and separately enabled REAL authenticated voice pilot")
        sub = parser.add_subparsers(dest="command", required=True)
        for name in ("privacy", "inspect-config", "evaluate-synthetic", "evaluate-timings",
                     "confirmation-policy", "evaluate-usability", "evaluate-threats", "evaluate-all"):
            sub.add_parser(name)
        for name in ("status", "begin", "resume", "owner", "nonowner", "holdout", "replay", "freeze",
                     "evaluate", "approve", "results", "suspend", "revoke", "delete", "voice-pilot"):
            child = sub.add_parser(name)
            child.add_argument("--profile", type=UUID, required=True)
            if name in {"owner", "nonowner", "holdout", "replay", "voice-pilot"}:
                child.add_argument("--timings", action="store_true", help="Opt-in numerical timings only; never saved")
            if name in {"owner", "nonowner", "holdout", "replay"}:
                child.add_argument("--environment", choices=("quiet", "different_environment"), required=True)
            if name == "nonowner":
                child.add_argument("--participant", type=UUID, required=True)
        args = parser.parse_args(argv)
        cfg = settings or Settings()
        if args.command == "privacy":
            write(PRIVACY)
            return 0
        if args.command == "inspect-config":
            write(cfg.owner.model_dump_json())
            return 0
        if args.command == "evaluate-synthetic":
            from app.owner.evaluation import evaluate
            write(json.dumps(evaluate()))
            return 0
        if args.command == "evaluate-timings":
            from app.owner.timing_evaluation import evaluate
            write(json.dumps(evaluate()))
            return 0
        if args.command == "confirmation-policy":
            from app.owner.confirmation import policy_document
            write(json.dumps(policy_document()))
            return 0
        if args.command in {"evaluate-usability", "evaluate-threats", "evaluate-all"}:
            from app.owner.security_evaluation import usability, threats, evaluate_all
            evaluate = {"evaluate-usability": usability, "evaluate-threats": threats,
                        "evaluate-all": evaluate_all}[args.command]
            write(json.dumps(evaluate()))
            return 0
        tty = interactive or (lambda: sys.stdin.isatty() and sys.stdout.isatty())
        if not tty():
            raise OwnerError("consent_required")
        if getattr(args, "timings", False):
            timing_report = timing.Report()
            timing_token = timing.activate(timing_report)
        if args.command == "voice-pilot":
            if not cfg.owner.pilot_enabled or not cfg.speaker_verification_enabled:
                raise OwnerError("access_denied")
        elif args.command not in {"status", "results", "resume", "revoke", "suspend", "delete"} and not cfg.owner.calibration_enabled:
            raise OwnerError("access_denied")
        if factory is None:
            from app.owner.runtime import Runtime
            factory = Runtime
        runtime = factory(cfg, read=read, write=write)
        service = runtime.calibration()
        if args.command in {"status", "results", "resume"}:
            write(json.dumps(service.status(args.profile)))
            return 0
        write(PRIVACY)
        if args.command == "voice-pilot":
            write("REAL AUTHENTICATED VOICE PILOT: one challenge, a separately verified command, and fresh voice confirmation for changes. No background listening.")
        action = args.command.upper()
        consent = "CONSENT " + action
        if action == "DELETE":
            consent += " " + str(args.profile)
        if read("Type exactly " + consent + ": ") != consent:
            raise OwnerError("consent_required")
        if args.command == "begin":
            result = service.begin(args.profile, consent=True)
        elif args.command in {"owner", "nonowner", "holdout", "replay"}:
            if args.command == "nonowner" and read("Non-owner speaker: type I CONSENT TO THIS TRIAL: ") != "I CONSENT TO THIS TRIAL":
                raise OwnerError("consent_required")
            if args.command == "replay":
                write("Wrong-phrase challenge test: speak the displayed alternate phrase; expected challenge rejection. Not a strong replay/liveness test.")
            timing.begin("total_after_consent")
            timing.begin("consent_to_phrase_display")
            participant = getattr(args, "participant", None)
            trial_consent = TrialConsent(profile_id=args.profile, group=args.command,
                                         environment=args.environment, participant=participant)
            result = service.collect(args.profile, args.command, args.environment,
                                     consent=trial_consent, participant=participant)
        elif args.command == "freeze":
            result = service.freeze(args.profile)
        elif args.command == "evaluate":
            result = service.evaluate(args.profile)
        elif args.command == "approve":
            result = service.approve(args.profile, consent=True)
        elif args.command in {"suspend", "revoke", "delete"}:
            result = service.change(args.profile, args.command, consent=True)
        else:
            timing.begin("total_after_consent")
            timing.begin("consent_to_phrase_display")
            result = runtime.pilot(service).run(args.profile).model_dump(mode="json")
        timing.end("total_after_consent")
        write(json.dumps(result))
        return 2 if result.get("status") in {"blocked", "cancelled"} else 0
    except (KeyboardInterrupt, EOFError):
        write('{"status":"cancelled","reason":"cancelled"}')
        return 2
    except Exception as error:
        reason = error.code if type(error) is OwnerError else "access_denied"
        write(json.dumps({"status": "blocked", "reason": reason}))
        return 2

    finally:
        if timing_token is not None:
            timing.end("total_after_consent")
            timing.deactivate(timing_token)
            write(json.dumps(timing_report.document()))


if __name__ == "__main__":
    raise SystemExit(main())
