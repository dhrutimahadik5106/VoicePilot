"""Explicit evaluation tools. Defaults never open audio, display private text or export."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from app.audio.models import AudioFormat, RecordedAudio
from app.core.config import Settings
from app.evaluation.dataset import load_manifest, validate_manifest
from app.evaluation.models import Manifest
from app.evaluation.stt import private_audio_loader, run_evaluation
from app.stt.context import Vocabulary, PUBLIC_CONTEXT, load_vocabulary, load_overlay, public_inspection
from app.stt.models import TranscriptSegment, TranscriptionResult
from app.stt.parity import ComparisonEngine
from app.stt.refinement import refine


def fictional_manifest():
    rows = []
    for index, (language, text) in enumerate((("en", "open Spotify"), ("hi", "\u0915\u0943 \u092a\u092f\u093e"),
                                               ("mr", "\u0927\u0928\u094d\u092f \u0935\u093e\u0926"), ("mixed", "hello VoicePilot"))):
        rows.append({"recording_id": f"rec_demo000{index}", "source_type": "synthetic_text", "ground_truth": text,
                     "review_status": "reviewed", "language": language, "script": "Latin" if language in {"en", "mixed"} else "Devanagari",
                     "speaker": "spk_0000000000000000", "session": "session_demo0000", "recording_group": f"group_demo000{index}",
                     "split": "development", "noise_condition": "unknown", "content": "speech", "usable_speech": True,
                     "task": "command" if index == 0 else "dictation", "expected_intent": "open_application" if index == 0 else None,
                     "expected_entities": {"application": "Spotify"} if index == 0 else {},
                     "expected_canonical": "Open Spotify" if index == 0 else None, "expected_confirmation": index != 0})
    return Manifest.model_validate({"schema_version": "1.0", "rows": rows})


def fictional_demo():
    manifest = fictional_manifest()
    # Explicit fake outputs; no Whisper, VAD, microphone, network or files.
    texts = [r.ground_truth for r in manifest.rows]
    class Tokenizer:
        def encode(self, text, **kwargs): return SimpleNamespace(ids=list(range(len(text))))
    class Model:
        supported_languages = ["en", "hi", "mr"]
        hf_tokenizer = Tokenizer()
        def __init__(self): self.index = 0
        def transcribe(self, samples, **kwargs):
            text = texts[self.index]
            self.index += 1
            return iter([SimpleNamespace(text=text, start=0, end=.5, words=None)]), SimpleNamespace(
                language=kwargs["language"] or "en", language_probability=.9, duration_after_vad=1.0)
    def factory(settings, **kwargs):
        return ComparisonEngine(settings, model_factory=lambda *a, **kw: Model(), **kwargs)
    report = run_evaluation(manifest, Settings(), audio_loader=lambda _: RecordedAudio(
        format=AudioFormat(), samples=np.zeros((16000, 1), dtype=np.int16)), engine_factory=factory)
    report["evidence"] = "fictional_fake_pipeline_demo_not_accuracy_evidence"
    return report


def inspect_refinement(text, language):
    result = TranscriptionResult(audio_id=uuid4(), language=language, text=text.strip(),
        segments=(TranscriptSegment(text=text, start=0, end=1),), processing_duration=0,
        source_audio_duration=1, model_name="fictional-inspection", device="cpu", compute_type="int8", status="succeeded")
    return refine(result).inspection()


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_evaluation_arguments")


def main(argv=None, *, write=print):
    parser = SafeArgumentParser(description="Private evaluation foundation; real audio requires explicit consent flag.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-schema")
    commands.add_parser("demo")
    context = commands.add_parser("inspect-context")
    context.add_argument("--language", choices=["en", "hi", "mr", "mixed", "auto"], default="auto")
    shadow = commands.add_parser("inspect-refinement")
    shadow.add_argument("--text", required=True)
    shadow.add_argument("--language", choices=["en", "hi", "mr"], required=True)
    for name in ("validate-manifest", "run"):
        command = commands.add_parser(name)
        command.add_argument("--private-root", required=True, type=Path)
        command.add_argument("--manifest", required=True, type=Path)
        if name == "run":
            command.add_argument("--consent-evaluation", action="store_true")
            command.add_argument("--split", choices=["development", "validation", "test"])
            command.add_argument("--show-utterances", action="store_true", help="Explicitly display private local per-utterance details")
            command.add_argument("--private-overlay", type=Path)
            command.add_argument("--language", choices=["en", "hi", "mr", "auto"])
    try:
        args = parser.parse_args(argv)
        if args.command == "validate-schema":
            vocabulary = load_vocabulary()
            schema = json.loads(PUBLIC_CONTEXT.with_name("context-schema-v1.json").read_text(encoding="utf-8"))
            if schema != Vocabulary.model_json_schema(): raise ValueError()
            validate_manifest(fictional_manifest(), public_vocabulary=vocabulary)
            output = {"valid": True, "context_entries": len(vocabulary.entries), "manifest_schema_version": "1.0"}
        elif args.command == "demo": output = fictional_demo()
        elif args.command == "inspect-context": output = public_inspection(args.language)
        elif args.command == "inspect-refinement": output = inspect_refinement(args.text, args.language)
        else:
            vocabulary = load_vocabulary()
            manifest = load_manifest(args.manifest, root=args.private_root, public_vocabulary=vocabulary)
            if args.command == "validate-manifest":
                output = {"valid": True, "row_count": len(manifest.rows)}
            else:
                if not args.consent_evaluation: raise ValueError()
                if args.split:
                    selected = tuple(r for r in manifest.rows if r.split == args.split)
                    if not selected: raise ValueError()
                    manifest = Manifest(schema_version="1.0", rows=selected)
                settings = Settings(stt_local_files_only=True, stt_language=args.language)
                overlay = load_overlay(args.private_overlay, args.private_root) if args.private_overlay else None
                output = run_evaluation(manifest, settings, vocabulary=vocabulary, overlay=overlay,
                    audio_loader=private_audio_loader(args.private_root, settings.stt_max_duration_seconds),
                    include_utterances=args.show_utterances, private_root=args.private_root,
                    language_mode="auto" if args.language == "auto" else "manifest")
        write(json.dumps(output, ensure_ascii=True, indent=2, allow_nan=False))
        return 0
    except (KeyboardInterrupt, EOFError):
        write('{"status":"cancelled"}')
        return 0
    except Exception:
        write('{"error":"invalid_evaluation_request"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
