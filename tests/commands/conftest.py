import importlib.abc
import os
import socket
import subprocess
import sys
import webbrowser

import pytest

from app.commands.resolver import CommandResolver


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
