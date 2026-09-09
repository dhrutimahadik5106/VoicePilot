"""Inspect distribution metadata only; never import future integrations."""
import sys
from importlib.metadata import PackageNotFoundError, version

import pytest


def distribution_version(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def test_python_and_existing_virtual_environment():
    assert sys.version_info[:3] == (3, 12, 10)
    assert sys.prefix != sys.base_prefix


@pytest.mark.parametrize("package", ["pydantic", "pydantic-settings", "pytest"])
def test_required_packages_present(package):
    assert distribution_version(package)


@pytest.mark.parametrize("package", [
    "sounddevice", "faster-whisper", "onnxruntime", "langgraph", "ollama",
    "resemblyzer", "webrtcvad",
])
def test_optional_package_detection(package, record_property):
    installed = distribution_version(package)
    record_property(package, installed or "not installed")
    assert installed is None or isinstance(installed, str)
