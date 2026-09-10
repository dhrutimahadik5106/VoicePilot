import json

from app.commands.cli import main


def test_text_only_cli_does_not_execute():
    output = []
    assert main(["resolve", "open Spotify"], write=output.append) == 0
    result = json.loads(output[0])
    assert result["canonical_command"] == "Open Spotify"
    assert result["execution_permitted"] is False


def test_shell_text_is_not_executed_or_read():
    output = []
    raw = "open Spotify; type C:\\Users\\private.txt"
    assert main(["resolve", raw], write=output.append) == 0
    result = json.loads(output[0])
    assert result["raw_transcript"] == raw and result["requires_confirmation"]


def test_dataset_validation_and_evaluation_cli():
    for command in ("validate-dataset", "evaluate"):
        output = []
        assert main([command], write=output.append) == 0
        result = json.loads(output[0])
        assert result["rows"] == 80


def test_bad_dataset_returns_safe_error(tmp_path):
    output = []
    assert main(["evaluate", "--dataset", str(tmp_path / "missing.jsonl")], write=output.append) == 2
    assert json.loads(output[0]) == {"error": "invalid_command_input_or_dataset"}

def test_cli_preserves_received_title_spacing():
    for raw in ("Hey Voice Pilot, open Spotify and play Taare Zameen Par.",
                "Hey Voice Pilot, open Spotify and play TaareZameen Par."):
        output = []
        assert main(["resolve", raw], write=output.append) == 0
        assert json.loads(output[0])["raw_transcript"] == raw
