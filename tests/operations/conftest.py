"""Deny every real OS integration; allow only controlled temporary artifact I/O."""
import builtins
import ctypes
import io
import os
from pathlib import Path
import socket
import subprocess
import pytest


@pytest.fixture(autouse=True)
def guarded(monkeypatch, tmp_path):
    original_import = builtins.__import__
    def importing(name, *args, **kwargs):
        if name.split(".")[0] in {"sounddevice", "sherpa_onnx", "faster_whisper", "torch", "pyautogui", "webbrowser", "requests", "httpx"}:
            raise AssertionError("forbidden_integration")
        return original_import(name, *args, **kwargs)
    def denied(*args, **kwargs):
        raise AssertionError("forbidden_side_effect")
    monkeypatch.setattr(builtins, "__import__", importing)
    for owner, names in ((ctypes, ("WinDLL",)), (subprocess, ("Popen",)),
                         (os, ("system", "startfile")), (socket.socket, ("connect", "connect_ex"))):
        for name in names:
            monkeypatch.setattr(owner, name, denied)
    for owner in (builtins, io):
        original = owner.open
        def opened(file, *args, _original=original, **kwargs):
            if type(file) is not int and not Path(file).absolute().is_relative_to(tmp_path):
                raise AssertionError("outside_test_directory")
            return _original(file, *args, **kwargs)
        monkeypatch.setattr(owner, "open", opened)

    for name in ("open", "mkdir", "unlink", "remove"):
        original = getattr(os, name)
        def operation(path, *args, _original=original, **kwargs):
            if not Path(path).absolute().is_relative_to(tmp_path):
                raise AssertionError("outside_test_directory")
            return _original(path, *args, **kwargs)
        monkeypatch.setattr(os, name, operation)
