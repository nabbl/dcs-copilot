from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dcs_copilot.audio.devices import AudioDeviceStatus
from dcs_copilot.cli import status
from dcs_copilot.config import Settings


class FakeDcsBiosClient:
    def __init__(self, **_kwargs: object) -> None:
        self.connected = False
        self.frame_age = None
        self.current_aircraft = None
        self.parser = SimpleNamespace(error_count=0)

    async def listen_for(self, _duration: float) -> None:
        return None

    def close(self) -> None:
        return None


def test_status_reports_thin_client_resource_and_ai_boundary(monkeypatch) -> None:
    monkeypatch.setattr(status, "DcsBiosClient", FakeDcsBiosClient)
    monkeypatch.setattr(status, "_load_registry", lambda _settings: (None, "missing"))
    monkeypatch.setattr(
        status,
        "inspect_audio_devices",
        lambda _input, _output: AudioDeviceStatus("Test Mic", "Test Headset", True),
    )
    lines, exit_code = asyncio.run(status.collect_status(Settings(), wait=0))
    assert exit_code == 0
    assert "Cloud: not probed; use --wait 0.25 or longer" in lines
    assert "Authenticated: no" in lines
    assert "Recorded events: 0" in lines
    assert "Speech mode: NORMAL" in lines
    assert "Mute: F14 (Windows only)" in lines
    assert "Microphone: Test Mic (not opened)" in lines
    assert "Output: Test Headset (not opened)" in lines
    assert "AI inference running locally: NO" in lines
    assert any(line.startswith("Client RAM: ") for line in lines)
