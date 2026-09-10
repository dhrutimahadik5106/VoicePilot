"""Text-only CLI: proposes interpretations, validates data, evaluates; never executes."""
import argparse
import json
from pathlib import Path

from app.commands.dataset import validate_dataset
from app.commands.evaluate import evaluate
from app.commands.models import ResolverConfig
from app.commands.registry import DATA_DIR
from app.commands.resolver import CommandResolver


def main(argv=None, *, write=print):
    parser = argparse.ArgumentParser(description="Non-executing VoicePilot command interpretation")
    parser.add_argument("--registry-dir", type=Path, default=DATA_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("transcript")
    resolve.add_argument("--language", choices=["en", "hi", "mr", "mixed"], default="mixed")
    resolve.add_argument("--acceptance-threshold", type=float, default=.95)
    for name in ("validate-dataset", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", type=Path, default=DATA_DIR / "seed-v1.jsonl")
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            resolver = CommandResolver.from_directory(args.registry_dir,
                ResolverConfig(acceptance_threshold=args.acceptance_threshold))
            output = resolver.resolve(args.transcript, language=args.language).model_dump(mode="json")
        else:
            rows = validate_dataset(args.dataset, args.registry_dir)
            output = {"valid": True, "rows": len(rows), "schema_version": "1.0"}
            if args.command == "evaluate":
                output = evaluate(rows, CommandResolver.from_directory(args.registry_dir))
        # JSON escapes terminal controls; transcript output is explicit, never logged.
        write(json.dumps(output, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError):
        write('{"error": "invalid_command_input_or_dataset"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
