"""Deny hardware, real adapters and filesystem access during every execution test."""
import builtins
import io
import os
from pathlib import Path
import socket
import subprocess
import numpy
import pytest


@pytest.fixture(autouse=True)
def no_real_integrations(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"sounddevice", "sherpa_onnx", "faster_whisper", "torch",
                                  "onnxruntime", "pyautogui", "webbrowser", "requests", "httpx"}:
            raise AssertionError("forbidden_integration")
        return original(name, *args, **kwargs)
    def blocked(*args, **kwargs):
        raise AssertionError("forbidden_side_effect")
    monkeypatch.setattr(builtins, "__import__", guarded)
    for owner, names in ((builtins, ("open",)), (io, ("open",)),
                         (subprocess, ("Popen",)), (socket, ("create_connection",)),
                         (socket.socket, ("connect", "connect_ex")),
                         (os, ("system", "startfile", "open", "unlink", "remove", "mkdir", "rename", "replace")),
                         (Path, ("open", "read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "unlink"))):
        for name in names:
            monkeypatch.setattr(owner, name, blocked)
