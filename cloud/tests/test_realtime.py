from __future__ import annotations

import asyncio

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.voice import VoiceAnnouncement, VoiceTurn, VoiceTurnResult
from dcs_copilot_protocol import (
    AircraftChanged,
    AircraftEvent,
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
            websocket.send_text(
                ControlMessage(
                    "authenticate",
                    {"access_token": "test-token", "device_id": "device-1"},
                ).to_json()
            )
            assert receive_control(websocket).payload["code"] == "already_authenticated"
            websocket.send_text(
                ControlMessage(
                    "session.start",
                    {"session_id": "other", "audio": AudioFormat().to_dict()},
                ).to_json()
            )
            assert (
                receive_control(websocket).payload["code"] == "session_already_active"
            )
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
            "proactive_events": True,
            "accounts": True,
            "memory": True,
            "habits": True,
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
        self.announcements: list[VoiceAnnouncement] = []
        self._release = asyncio.Event()

    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        self.turn = turn
        await on_audio(b"\x10\x20" * 240)
        if self.block:
            await self._release.wait()
        return VoiceTurnResult("Hello?", "Ready.")

    async def announce(self, announcement, on_audio) -> str:
        self.announcements.append(announcement)
        await on_audio(b"\x50\x60" * 240)
        if self.block:
            await self._release.wait()
        return announcement.text

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
        transcript = receive_control(websocket)
        assert transcript.type == "pilot.text"
        assert transcript.payload == {"text": "Hello?"}
        response = receive_control(websocket)
        assert response.type == "assistant.text"
        assert response.payload == {"text": "Ready."}
    assert pipeline.turn is not None
    assert pipeline.turn.audio == b"\x01\x02" * 320
    assert pipeline.turn.input_format.sample_rate == 16_000
    assert pipeline.turn.output_format.sample_rate == 24_000
    assert pipeline.closed


def test_aircraft_change_recreates_voice_pipeline_with_clean_context() -> None:
    pipelines: list[FakeVoicePipeline] = []

    def pipeline_factory(_settings: CloudSettings) -> FakeVoicePipeline:
        pipeline = FakeVoicePipeline()
        pipelines.append(pipeline)
        return pipeline

    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=pipeline_factory,
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
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).type == "pilot.text"
        assert receive_control(websocket).type == "assistant.text"
        assert len(pipelines) == 1

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 1, 2, b"\x05\x06" * 320).to_bytes()
        )
        websocket.send_text(AircraftChanged(None).to_control().to_json())
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"
        assert pipelines[0].closed

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 2, 3, b"\x03\x04" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        receipt = receive_control(websocket)
        assert receipt.payload["event_type"] == "utterance.received"
        assert receipt.payload["audio_bytes"] == 640
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).type == "pilot.text"
        assert receive_control(websocket).type == "assistant.text"
        assert len(pipelines) == 2
        assert pipelines[1] is not pipelines[0]


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
            )
            .to_control()
            .to_json()
        )

        output = MediaPacket.from_bytes(websocket.receive_bytes())
        assert output.kind is MediaKind.AUDIO_OUTPUT
        assert output.payload == b"\x30\x40" * 240
        transcript = receive_control(websocket)
        assert transcript.type == "pilot.text"
        assert transcript.payload == {"text": "What did I forget?"}
        response = receive_control(websocket)
        assert response.type == "assistant.text"
        assert response.payload == {"text": "Your refueling probe is still out."}
        assert response.correlation_id is not None


def proactive_event(*, status: str = "RAISED") -> AircraftEvent:
    return AircraftEvent(
        event_id="event-1",
        rule_id="FA18_REFUELING_PROBE_LEFT_OUT",
        status=status,
        severity="ADVISORY",
        aircraft="FA-18C_hornet",
        flight_phase="CRUISE",
        message="Refueling probe is still out.",
        data={"flight_phase": "CRUISE"},
    )


def test_semantic_event_streams_proactive_cloud_tts() -> None:
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
        request = proactive_event().to_control()
        websocket.send_text(request.to_json())
        output = MediaPacket.from_bytes(websocket.receive_bytes())
        response = receive_control(websocket)
        websocket.send_text(request.to_json())
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert output.kind is MediaKind.AUDIO_OUTPUT
    assert output.payload == b"\x50\x60" * 240
    assert response.payload == {
        "text": "Refueling probe is still out.",
        "proactive": True,
        "event_id": "event-1",
    }
    assert response.correlation_id == request.message_id
    assert pipeline.announcements[0].input_format.sample_rate == 16_000
    assert pipeline.announcements[0].output_format.sample_rate == 24_000
    assert len(pipeline.announcements) == 1


def test_proactive_event_is_suppressed_while_ptt_is_active() -> None:
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
        websocket.send_text(proactive_event().to_control().to_json())
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert pipeline.announcements == []


def test_event_resolution_cancels_in_progress_proactive_speech() -> None:
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
        websocket.send_text(proactive_event().to_control().to_json())
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        websocket.send_text(proactive_event(status="RESOLVED").to_control().to_json())
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert pipeline.interrupt_calls >= 1
