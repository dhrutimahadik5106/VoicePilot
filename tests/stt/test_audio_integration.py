import subprocess
from pathlib import Path

from app.audio.recorder import SoundDeviceRecorder
from app.core.config import Settings
from app.stt.faster_whisper_engine import FasterWhisperEngine
from app.stt.service import TranscriptionService
from tests.audio.test_recorder import FakeBackend
from tests.stt import FakeModel, isolated_stt


def test_phase_two_fake_capture_to_fake_model_without_files(tmp_path):
    settings = Settings()
    capture = SoundDeviceRecorder(settings, backend=FakeBackend()).record(1, lambda: "stop")
    model = FakeModel()
    engine = FasterWhisperEngine(settings, model_factory=lambda *a, **k: model)
    result = TranscriptionService(settings, engine).transcribe_audio(capture.audio)
    assert result.text == "hello" and result.source_audio_duration == .01
    assert list(tmp_path.iterdir()) == []


def test_imports_do_not_load_model_or_access_hardware(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import os
import socket
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'faster_whisper', 'ctranslate2', 'sounddevice'}:
            raise AssertionError('Unexpected model/hardware import')
sys.meta_path.insert(0, Block())
def denied(*args, **kwargs):
    raise AssertionError('Unexpected network access')
socket.socket.connect = denied
socket.create_connection = denied
import app.stt, app.stt.contracts, app.stt.models
import app.stt.faster_whisper_engine, app.stt.service, app.stt.cli
import app.stt.audio_preprocessing, app.stt.parity
from app.core.config import Settings
from app.stt.faster_whisper_engine import FasterWhisperEngine
os.chdir(sys.argv[1])
FasterWhisperEngine(Settings())
assert not os.listdir('.')
"""
    completed = subprocess.run(
        [str(root / "venv" / "Scripts" / "python.exe"), "-B", "-c", script, str(tmp_path)],
        cwd=root, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
