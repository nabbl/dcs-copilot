from __future__ import annotations

from uuid import uuid4

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.tools import (
    AIRCRAFT_TOOL_NAMES,
    AircraftToolRequest,
    ToolProtocolError,
)
from dcs_copilot_cloud.voice import VoiceTurn, VoiceTurnResult
from dcs_copilot_protocol import (
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
    TelemetryCatalog,
    TelemetrySnapshot,
)
from fastapi.testclient import TestClient


def receive_control(websocket) -> ControlMessage:
    return ControlMessage.from_json(websocket.receive_text())


def authenticate_and_start(websocket) -> None:
    assert receive_control(websocket).type == "hello"
    websocket.send_text(
        ControlMessage(
            "authenticate",
            {"access_token": "test-token", "device_id": "device-1"},
        ).to_json()
    )
    assert receive_control(websocket).payload["authenticated"] is True
    websocket.send_text(
        ControlMessage(
            "session.start",
            {
                "session_id": "session-1",
                "input_audio": AudioFormat().to_dict(),
                "output_audio": AudioFormat(sample_rate=24_000).to_dict(),
            },
        ).to_json()
    )
    assert receive_control(websocket).payload["session_active"] is True


def test_aircraft_tool_request_validates_known_names() -> None:
    request = AircraftToolRequest.create("get_aircraft_state", {"fields": ["connected"]})
    assert request.tool == "get_aircraft_state"

    try:
        AircraftToolRequest.create("nonexistent_tool", {})
    except ToolProtocolError:
        pass
    else:
        raise AssertionError("expected ToolProtocolError for an unknown tool name")


def test_aircraft_tool_names_are_complete() -> None:
    assert set(AIRCRAFT_TOOL_NAMES) == {
        "get_aircraft_state",
        "get_active_issues",
        "get_recent_events",
        "get_flight_phase",
        "get_checklist_status",
        "get_missing_checklist_items",
        "start_guided_checklist",
        "get_next_checklist_item",
        "confirm_manual_checklist_item",
        "stop_guided_checklist",
    }
    assert "get_aircraft_state" in AIRCRAFT_TOOL_NAMES
    assert "get_missing_checklist_items" in AIRCRAFT_TOOL_NAMES


class ConnectedStateVoicePipeline:
    def __init__(self) -> None:
        self.closed = False

    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        assert request_tool is not None
        result = await request_tool("get_aircraft_state", {"fields": ["connected"]})
        connected = result["fields"]["connected"]["value"]
        await on_audio(b"\x30\x40" * 240)
        return VoiceTurnResult("Status?", f"Aircraft connected: {connected}.")

    async def announce(self, announcement, on_audio) -> str:
        await on_audio(b"\x50\x60" * 240)
        return announcement.text

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def test_aircraft_tool_executed_locally_via_app() -> None:
    pipeline = ConnectedStateVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
    ):
        authenticate_and_start(websocket)

        epoch = str(uuid4())
        websocket.send_text(
            TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, []).to_control().to_json()
        )
        websocket.send_text(
            TelemetrySnapshot(epoch, 1, "FA-18C_hornet", 0, 1, [])
            .to_control()
            .to_json()
        )
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).payload["kind"] == "cockpit_welcome"

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"

        # No tool.request wire message: the very next frame is the audio output.
        output = MediaPacket.from_bytes(websocket.receive_bytes())
        assert output.kind is MediaKind.AUDIO_OUTPUT
        assert receive_control(websocket).payload == {"text": "Status?"}
        response = receive_control(websocket)
        assert response.payload == {"text": "Aircraft connected: True."}


class UnknownToolVoicePipeline:
    def __init__(self) -> None:
        self.closed = False

    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        assert request_tool is not None
        result = await request_tool("not_a_real_tool", {})
        assert result["error"]["code"] == "tool_not_allowlisted"
        await on_audio(b"\x30\x40" * 240)
        return VoiceTurnResult("What tools exist?", "That tool isn't available.")

    async def announce(self, announcement, on_audio) -> str:
        await on_audio(b"\x50\x60" * 240)
        return announcement.text

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def test_unknown_tool_returns_not_allowlisted_error() -> None:
    pipeline = UnknownToolVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
    ):
        authenticate_and_start(websocket)

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"

        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).payload == {"text": "What tools exist?"}
        response = receive_control(websocket)
        assert response.payload == {"text": "That tool isn't available."}
