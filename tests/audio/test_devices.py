from types import SimpleNamespace

import pytest

from app.audio.contracts import AudioError
from app.audio.devices import list_input_devices, select_input_device
from app.audio.models import ErrorCode


def backend():
    return SimpleNamespace(
        default=SimpleNamespace(device=(1, 0)),
        query_devices=lambda: [
            dict(name="output", max_input_channels=0, default_samplerate=48000),
            dict(name="input", max_input_channels=2, default_samplerate=16000),
        ],
    )


def test_filtering_and_selection():
    fake = backend()
    assert [item.index for item in list_input_devices(fake)] == [1]
    assert select_input_device(None, fake).index == 1
    assert select_input_device("INPUT", fake).index == 1
    assert select_input_device(1, fake).name == "input"


@pytest.mark.parametrize("identifier", [0, 999, "unknown"])
def test_missing_selected_device(identifier):
    with pytest.raises(AudioError, match="device_not_found"):
        select_input_device(identifier, backend())


def test_no_input_devices():
    with pytest.raises(AudioError, match="device_not_found"):
        list_input_devices(SimpleNamespace(query_devices=lambda: []))


def test_permission_failure_is_safe():
    def query():
        raise PermissionError("sensitive native exception")
    with pytest.raises(AudioError) as error:
        list_input_devices(SimpleNamespace(query_devices=query))
    assert error.value.code == ErrorCode.PERMISSION_DENIED
    assert str(error.value) == "permission_denied"


def test_missing_default_does_not_choose_another_device():
    fake = backend()
    fake.default.device = (-1, 0)
    with pytest.raises(AudioError, match="device_not_found"):
        select_input_device(None, fake)


def test_duplicate_name_is_rejected():
    fake = backend()
    fake.query_devices = lambda: [
        dict(name="same", max_input_channels=1, default_samplerate=16000),
        dict(name="same", max_input_channels=1, default_samplerate=16000),
    ]
    with pytest.raises(AudioError, match="device_not_found"):
        select_input_device("same", fake)
