from __future__ import annotations

import sys
from types import SimpleNamespace

from dcs_copilot.audio.devices import AudioDevice, discover_audio_devices


class FakePyAudio:
    def __init__(self) -> None:
        self.terminated = False

    def get_device_count(self) -> int:
        return 3

    def get_device_info_by_index(self, index: int) -> dict[str, object]:
        return (
            {"name": "Mic", "maxInputChannels": 1, "maxOutputChannels": 0},
            {"name": "Headset", "maxInputChannels": 0, "maxOutputChannels": 2},
            {"name": "Duplex", "maxInputChannels": 1, "maxOutputChannels": 2},
        )[index]

    def terminate(self) -> None:
        self.terminated = True


def test_audio_discovery_reports_input_and_output_capabilities(monkeypatch) -> None:
    audio = FakePyAudio()
    monkeypatch.setitem(
        sys.modules,
        "pyaudio",
        SimpleNamespace(PyAudio=lambda: audio),
    )

    assert discover_audio_devices() == [
        AudioDevice(0, "Mic", 1, 0),
        AudioDevice(1, "Headset", 0, 2),
        AudioDevice(2, "Duplex", 1, 2),
    ]
    assert audio.terminated
