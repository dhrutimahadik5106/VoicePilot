import importlib.abc
import os
import socket
import subprocess
import sys
import webbrowser

import pytest

from app.commands.resolver import CommandResolver

_ORIGINAL_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def no_external_actions(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network, execution and hardware are forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(os, "system", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    monkeypatch.setattr(webbrowser, "open", blocked)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", blocked)
    class NoBackends(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"sounddevice", "faster_whisper", "ctranslate2", "pyautogui"}:
                raise AssertionError("Backend loading forbidden")
    monkeypatch.setattr(sys, "meta_path", [NoBackends(), *sys.meta_path])


@pytest.fixture
def resolver():
    return CommandResolver.from_directory()

@pytest.fixture
def cli_subprocess(monkeypatch):
    """Narrow exception: only this venv's text CLI, no shell or action backend."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    child_code = """
import os, runpy, socket, subprocess, sys, webbrowser
def blocked(*args, **kwargs):
    raise AssertionError('No external actions')
socket.socket.connect = blocked
socket.create_connection = blocked
os.system = blocked
subprocess.Popen = blocked
webbrowser.open = blocked
if hasattr(os, 'startfile'):
    os.startfile = blocked
sys.argv = ['app.commands.cli', 'resolve', sys.argv[1]]
runpy.run_module('app.commands.cli', run_name='__main__')
"""
    def run(raw):
        with monkeypatch.context() as scoped:
            scoped.setattr(subprocess, "Popen", _ORIGINAL_POPEN)
            completed = subprocess.run(
                [str(root / "venv" / "Scripts" / "python.exe"), "-B", "-c", child_code, raw],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
                shell=False, check=True,
            )
        return completed.stdout
    return run
