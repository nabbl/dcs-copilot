from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dcs_copilot.audio.devices import AudioDeviceStatus
from dcs_copilot.cli import status
from dcs_copilot.config import Settings
from dcs_copilot_protocol import CoachCapabilitiesPayload


class FakeDcsBiosClient:
    def __init__(self, **_kwargs: object) -> None:
        self.connected = False
        self.frame_age = None
        self.current_aircraft = None
        self.parser = SimpleNamespace(error_count=0)

    async def listen_for(self, _duration: float) -> None:
        return None

    def decoded_snapshot(self) -> tuple[object, ...]:
        return ()

    def active_definitions(self) -> tuple[object, ...]:
        return ()

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
    assert "Active catalog outputs: 0" in lines
    assert "Available decoded outputs: 0" in lines
    assert all("Flight phase" not in line for line in lines)
    assert all("Active issues" not in line for line in lines)
    assert "Mute: F14 (Windows only)" in lines
    assert "Microphone: Test Mic (not opened)" in lines
    assert "Output: Test Headset (not opened)" in lines
    assert "AI inference running locally: NO" in lines
    assert any(line.startswith("Client RAM: ") for line in lines)


def test_coach_diagnostics_distinguish_blocked_world_export() -> None:
    lines = status._coach_status_lines(
        CoachCapabilitiesPayload(
            ownship_export=True,
            world_object_export=False,
            sensor_export=True,
            cockpit_state=True,
        ),
        cockpit_available=True,
        error=None,
    )

    assert "Ownship telemetry: AVAILABLE" in lines
    assert "World object export: BLOCKED" in lines
    assert "Formation Coach: UNAVAILABLE" in lines
    assert "CASE I Pattern Coach: UNAVAILABLE" in lines
    assert "Carrier Approach: UNAVAILABLE" in lines
    assert "Procedure Coach: AVAILABLE" in lines
