import ctypes
import pytest
from tests.execution.conftest import no_real_integrations


@pytest.fixture(autouse=True)
def no_native_apis(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("native_api_forbidden")
    monkeypatch.setattr(ctypes, "WinDLL", denied)
