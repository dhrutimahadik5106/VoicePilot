"""Active guards: only fixed public registries and pytest temporary files are readable."""
import builtins
import ctypes
import io
import os
from pathlib import Path
import socket
import subprocess
import pytest
from app.api.server import Handler, serve
from app.session.service import SessionService
from app.execution.cancellation import CancellationHub
from app.commands.registry import DATA_DIR
from app.launch.controller import LaunchController
from app.operations.controller import Controller


@pytest.fixture(autouse=True)
def guards(monkeypatch,tmp_path):
    original_import = builtins.__import__
    def imported(name,*args,**kwargs):
        if name.split(".")[0] in {"sounddevice","sherpa_onnx","faster_whisper","torch","onnxruntime","requests","httpx","webbrowser","pyautogui"}:
            raise AssertionError("forbidden_integration")
        return original_import(name,*args,**kwargs)
    def denied(*args,**kwargs): raise AssertionError("forbidden_side_effect")
    monkeypatch.setattr(builtins,"__import__",imported)
    for target,names in ((ctypes,("WinDLL",)),(subprocess,("Popen",)),(os,("system","startfile")),
                         (socket.socket,("connect","connect_ex","bind","listen"))):
        for name in names: monkeypatch.setattr(target,name,denied)
    monkeypatch.setattr(LaunchController,"run",denied)
    monkeypatch.setattr(Controller,"run",denied)
    allowed = {DATA_DIR / "aliases-v1.json", DATA_DIR / "intents-v1.json"}
    for target in (builtins,io):
        original = target.open
        def opened(path,*args,_original=original,**kwargs):
            if type(path) is int: raise AssertionError("private_file")
            selected = Path(path).absolute()
            mode = args[0] if args else kwargs.get("mode","r")
            if selected in allowed and not any(flag in mode for flag in "wax+"):
                return _original(path,*args,**kwargs)
            if not selected.is_relative_to(tmp_path): raise AssertionError("private_file")
            return _original(path,*args,**kwargs)
        monkeypatch.setattr(target,"open",opened)
    for name in ("open","mkdir","unlink","remove","replace"):
        original = getattr(os,name)
        def operation(path,*args,_original=original,**kwargs):
            if not Path(path).absolute().is_relative_to(tmp_path): raise AssertionError("private_file")
            return _original(path,*args,**kwargs)
        monkeypatch.setattr(os,name,operation)


@pytest.fixture
def service():
    clock = [0.]
    result = SessionService(clock=lambda:clock[0],hub=CancellationHub())
    result.test_clock = clock
    yield result
    result.close()
