import builtins
import os
import socket
import subprocess
import numpy as np
import pytest

@pytest.fixture(autouse=True)
def no_real_integrations(monkeypatch):
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name.split(".")[0] in {"sounddevice","sherpa_onnx","faster_whisper","torch","onnxruntime","pyautogui","webbrowser"}:
            raise AssertionError("forbidden_integration")
        return original(name,*args,**kwargs)
    def blocked(*args,**kwargs): raise AssertionError("forbidden_side_effect")
    monkeypatch.setattr(builtins,"__import__",guarded)
    monkeypatch.setattr(socket.socket,"connect",blocked)
    monkeypatch.setattr(socket,"create_connection",blocked)
    monkeypatch.setattr(subprocess,"Popen",blocked)
    monkeypatch.setattr(os,"system",blocked)
    monkeypatch.setattr(os,"startfile",blocked)
