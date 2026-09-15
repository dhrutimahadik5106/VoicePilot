"""Read-only status and in-memory synthetic evaluation; no live execution command."""
import argparse
import json
from app.execution.evaluation import evaluate
from app.execution.models import Configuration
from app.execution.registry import REGISTRY


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_command")


def main(argv=None, *, write=print):
    parser = Parser(description="Phase 5B fake-only inspection; real execution disabled")
    parser.add_argument("command", choices=("status", "registry", "evaluate"))
    try:
        args = parser.parse_args(argv)
        if args.command == "evaluate":
            report = evaluate()
        elif args.command == "registry":
            report = {"fake": True, "execution_permitted": False,
                      "adapters": [spec.model_dump(mode="json") for spec in REGISTRY.values()]}
        else:
            report = {"fake": True, "execution_permitted": False,
                      "production_authorization": "unavailable", "configuration": Configuration().model_dump()}
        write(json.dumps(report, sort_keys=True))
        return 2 if report.get("mismatches") else 0
    except Exception:
        write('{"reason":"invalid_request","fake":true,"execution_permitted":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
