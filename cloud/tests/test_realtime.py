from __future__ import annotations

import asyncio

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.voice import VoiceTurn, VoiceTurnResult
from dcs_copilot_protocol import (
    AircraftToolRequest,
    AircraftToolResult,
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
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
    authenticated = receive_control(websocket)
    assert authenticated.type == "connection.status"
    assert authenticated.payload["authenticated"] is True
    websocket.send_text(
        ControlMessage(
            "session.start",
            {
                "session_id": "session-1",
                "audio": AudioFormat().to_dict(),
            },
        ).to_json()
    )
    started = receive_control(websocket)
    assert started.payload["session_active"] is True


def test_ptt_audio_reaches_cloud_and_release_ends_turn() -> None:
    app = create_app(CloudSettings(dev_access_token="test-token"))
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(
                MediaKind.AUDIO_INPUT,
                0,
                1,
                b"\x01\x02" * 320,
            ).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        event = receive_control(websocket)
        assert event.type == "event"
        assert event.payload == {
            "event_type": "utterance.received",
            "session_id": "session-1",
            "audio_bytes": 640,
            "audio_chunks": 1,
            "duration_ms": 20,
        }
    assert len(app.state.received_utterances) == 1
    assert app.state.received_utterances[0].audio_bytes == 640


def test_unknown_message_is_nonfatal_and_invalid_token_closes() -> None:
    app = create_app(CloudSettings(dev_access_token="test-token"))
    with TestClient(app) as client:
        with client.websocket_connect("/v1/realtime") as websocket:
            authenticate_and_start(websocket)
            websocket.send_text(ControlMessage("future.message").to_json())
            error = receive_control(websocket)
            assert error.type == "error"
            assert error.payload["code"] == "unsupported_message"

        with client.websocket_connect("/v1/realtime") as websocket:
            assert receive_control(websocket).type == "hello"
            websocket.send_text(
                ControlMessage(
                    "authenticate",
                    {"access_token": "wrong", "device_id": "device-1"},
                ).to_json()
            )
            error = receive_control(websocket)
            assert error.payload["code"] == "authentication_failed"


def test_health_explicitly_reports_no_ai_pipeline() -> None:
    app = create_app(CloudSettings(dev_access_token="test-token"))
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {
            "status": "ok",
            "protocol_version": 1,
            "ai_inference": False,
            "voice_pipeline": "pipecat",
        }


def test_unauthenticated_connection_times_out() -> None:
    app = create_app(
        CloudSettings(
            dev_access_token="test-token",
            handshake_timeout_seconds=0.01,
        )
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        assert receive_control(websocket).type == "hello"
        error = receive_control(websocket)
        assert error.payload == {"code": "handshake_timeout", "fatal": True}


class FakeVoicePipeline:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.turn: VoiceTurn | None = None
        self.interrupt_calls = 0
        self.closed = False
        self._release = asyncio.Event()

    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        self.turn = turn
        await on_audio(b"\x10\x20" * 240)
        if self.block:
            await self._release.wait()
        return VoiceTurnResult("Hello?", "Ready.")

    async def interrupt(self) -> None:
        self.interrupt_calls += 1
        self._release.set()

    async def close(self) -> None:
        self.closed = True


def test_ptt_turn_streams_cloud_voice_audio_and_text() -> None:
    pipeline = FakeVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"
        output = MediaPacket.from_bytes(websocket.receive_bytes())
        assert output.kind is MediaKind.AUDIO_OUTPUT
        assert output.payload == b"\x10\x20" * 240
        response = receive_control(websocket)
        assert response.type == "assistant.text"
        assert response.payload == {"text": "Ready."}
    assert pipeline.turn is not None
    assert pipeline.turn.audio == b"\x01\x02" * 320
    assert pipeline.turn.input_format.sample_rate == 16_000
    assert pipeline.turn.output_format.sample_rate == 24_000
    assert pipeline.closed


def test_ptt_barge_in_interrupts_active_cloud_response() -> None:
    pipeline = FakeVoicePipeline(block=True)
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).type == "event"
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        websocket.send_text(ControlMessage("ptt.start").to_json())
    assert pipeline.interrupt_calls >= 1


class ToolCallingVoicePipeline(FakeVoicePipeline):
    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        self.turn = turn
        assert request_tool is not None
        result = await request_tool("get_active_issues", {})
        message = result["issues"][0]["message"]
        await on_audio(b"\x30\x40" * 240)
        return VoiceTurnResult("What did I forget?", message)


def test_complete_mocked_voice_tool_result_voice_round_trip() -> None:
    pipeline = ToolCallingVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"

        tool_control = receive_control(websocket)
        request = AircraftToolRequest.from_control(tool_control)
        assert request.tool == "get_active_issues"
        websocket.send_text(
            AircraftToolResult.success(
                request,
                {
                    "available": True,
                    "coverage": "AVAILABLE",
                    "unavailable_rule_ids": [],
                    "issues": [
                        {
                            "rule_id": "FA18_REFUELING_PROBE",
                            "severity": "ADVISORY",
                            "message": "Your refueling probe is still out.",
                            "explanation": "The local rule is active.",
                            "data": {},
                        }
                    ],
                },
            ).to_control().to_json()
        )

        output = MediaPacket.from_bytes(websocket.receive_bytes())
        assert output.kind is MediaKind.AUDIO_OUTPUT
        assert output.payload == b"\x30\x40" * 240
        response = receive_control(websocket)
        assert response.type == "assistant.text"
        assert response.payload == {"text": "Your refueling probe is still out."}
        assert response.correlation_id is not None
