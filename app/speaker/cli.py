"""Phase 4A metadata and synthetic tools only; no audio or filesystem loading."""
import argparse
import json
from app.core.config import Settings
from app.speaker.evaluate import synthetic_demo
from app.speaker.models import SpeakerProfile

class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")

def main(argv=None, *, write=print):
    parser = SafeParser(description="Phase 4A synthetic speaker foundation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect-status", "inspect-policy", "validate-schema", "enroll", "verify"):
        sub.add_parser(name)
    profiles = sub.add_parser("profiles")
    profiles.add_argument("action", choices=["list"])
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--synthetic", required=True, action="store_true")
    try:
        args = parser.parse_args(argv)
        settings = Settings()
        if args.command == "evaluate":
            result = synthetic_demo().model_dump(mode="json")
        elif args.command == "validate-schema":
            SpeakerProfile.model_json_schema()
            result = {"schema_version":1, "status":"valid", "biometric_values_displayed":False}
        elif args.command == "inspect-policy":
            result = {"status":"calibration_pending", "acceptance":settings.speaker.acceptance_threshold,
                      "review":settings.speaker.rejection_threshold, "authorizes_pipeline":False}
        else:
            result = {"status":"unavailable", "phase":"4A", "runtime":"not_provisioned",
                      "protection":"unavailable", "calibration":"pending", "spoof_assurance":"not_assessed"}
        write(json.dumps(result, sort_keys=True))
        return 2 if args.command in ("enroll", "verify", "profiles") else 0
    except Exception:
        write('{"status":"unavailable","reason":"invalid_configuration_or_arguments"}')
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
