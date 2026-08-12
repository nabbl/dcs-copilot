from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.voice import VoiceAnnouncement, VoiceTurn, VoiceTurnResult
from dcs_copilot_protocol import (
    AudioFormat,
    CatalogEntry,
    ControlIdentity,
    ControlMessage,
    DecodedValue,
    MediaKind,
    MediaPacket,
    TelemetryCatalog,
    TelemetryDelta,
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
    authenticated = receive_control(websocket)
    assert authenticated.type == "connection.status"
    assert authenticated.payload["authenticated"] is True
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
    started = receive_control(websocket)
    assert started.payload["session_active"] is True


def test_ptt_audio_reaches_cloud_and_release_ends_turn() -> None:
    app = create_app(CloudSettings(dev_access_token="test-token"))
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
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
        with client.websocket_connect("/v2/realtime") as websocket:
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
                    {
                        "session_id": "other",
                        "input_audio": AudioFormat().to_dict(),
                        "output_audio": AudioFormat(sample_rate=24_000).to_dict(),
                    },
                ).to_json()
            )
            assert (
                receive_control(websocket).payload["code"] == "session_already_active"
            )
            websocket.send_text(ControlMessage("future.message").to_json())
            error = receive_control(websocket)
            assert error.type == "error"
            assert error.payload["code"] == "unsupported_message"

        with client.websocket_connect("/v2/realtime") as websocket:
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
            "protocol_version": 2,
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
        client.websocket_connect("/v2/realtime") as websocket,
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
        client.websocket_connect("/v2/realtime") as websocket,
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


def test_new_epoch_catalog_resets_voice_pipeline_and_context() -> None:
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
        assert receive_control(websocket).type == "pilot.text"
        assert receive_control(websocket).type == "assistant.text"
        assert len(pipelines) == 1

        new_epoch = str(uuid4())
        websocket.send_text(
            TelemetryCatalog(new_epoch, 0, "FA-18C_hornet", 0, 1, [])
            .to_control()
            .to_json()
        )
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


BATTERY_IDENTITY = ControlIdentity("FA-18C_hornet", "BATTERY_SW", "integer", 0)
BATTERY_ENTRY = CatalogEntry(BATTERY_IDENTITY, "Battery switch", integer_max=2)


def test_cockpit_welcome_streams_once_on_complete_snapshot() -> None:
    pipeline = FakeVoicePipeline()
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
            TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, [BATTERY_ENTRY])
            .to_control()
            .to_json()
        )
        request = TelemetrySnapshot(
            epoch,
            1,
            "FA-18C_hornet",
            0,
            1,
            [DecodedValue(BATTERY_IDENTITY, True, 1)],
        ).to_control()
        websocket.send_text(request.to_json())

        output = MediaPacket.from_bytes(websocket.receive_bytes())
        response = receive_control(websocket)

    assert output.kind is MediaKind.AUDIO_OUTPUT
    assert output.payload == b"\x50\x60" * 240
    assert len(pipeline.announcements) == 1
    assert response.payload == {
        "text": pipeline.announcements[0].text,
        "proactive": True,
        "kind": "cockpit_welcome",
        "aircraft": "FA-18C_hornet",
    }
    assert response.correlation_id == request.message_id
    assert pipeline.announcements[0].input_format.sample_rate == 16_000
    assert pipeline.announcements[0].output_format.sample_rate == 24_000


def test_catalog_alone_does_not_trigger_welcome() -> None:
    pipeline = FakeVoicePipeline()
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
            TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, [BATTERY_ENTRY])
            .to_control()
            .to_json()
        )
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert pipeline.announcements == []


def test_duplicate_snapshot_rejected_and_welcome_fires_once() -> None:
    pipeline = FakeVoicePipeline()
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
            TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, [BATTERY_ENTRY])
            .to_control()
            .to_json()
        )
        websocket.send_text(
            TelemetrySnapshot(
                epoch,
                1,
                "FA-18C_hornet",
                0,
                1,
                [DecodedValue(BATTERY_IDENTITY, True, 1)],
            )
            .to_control()
            .to_json()
        )
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).payload["kind"] == "cockpit_welcome"

        websocket.send_text(
            TelemetrySnapshot(
                epoch,
                2,
                "FA-18C_hornet",
                0,
                1,
                [DecodedValue(BATTERY_IDENTITY, True, 0)],
            )
            .to_control()
            .to_json()
        )
        error = receive_control(websocket)
        assert error.payload["code"] == "invalid_message"

    assert len(pipeline.announcements) == 1


def test_ptt_barge_in_interrupts_active_cloud_response() -> None:
    pipeline = FakeVoicePipeline(block=True)
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
        assert receive_control(websocket).type == "event"
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        websocket.send_text(ControlMessage("ptt.start").to_json())
    assert pipeline.interrupt_calls >= 1


class BackendToolVoicePipeline(FakeVoicePipeline):
    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        self.turn = turn
        assert request_tool is not None
        result = await request_tool("get_aircraft_state", {"fields": ["connected"]})
        assert result["fields"]["connected"]["value"] is True
        await on_audio(b"\x30\x40" * 240)
        return VoiceTurnResult("Status?", "Aircraft is connected.")


def establish_connected_state(websocket) -> None:
    """Send a minimal catalog+snapshot pair and consume the resulting welcome."""
    epoch = str(uuid4())
    websocket.send_text(
        TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, []).to_control().to_json()
    )
    websocket.send_text(
        TelemetrySnapshot(epoch, 1, "FA-18C_hornet", 0, 1, []).to_control().to_json()
    )
    assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
        MediaKind.AUDIO_OUTPUT
    )
    assert receive_control(websocket).payload["kind"] == "cockpit_welcome"


def test_backend_aircraft_tool_executes_locally_no_wire_messages() -> None:
    pipeline = BackendToolVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        establish_connected_state(websocket)

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"

        # No tool.request wire message appears: the very next frame is audio output.
        output = MediaPacket.from_bytes(websocket.receive_bytes())
        assert output.kind is MediaKind.AUDIO_OUTPUT
        transcript = receive_control(websocket)
        assert transcript.payload == {"text": "Status?"}
        response = receive_control(websocket)
        assert response.payload == {"text": "Aircraft is connected."}


class ChecklistVoicePipeline(FakeVoicePipeline):
    async def respond(
        self, turn: VoiceTurn, on_audio, request_tool=None
    ) -> VoiceTurnResult:
        self.turn = turn
        assert request_tool is not None
        result = await request_tool(
            "get_missing_checklist_items", {"checklist_id": "fa18c_startup"}
        )
        response = f"Found {len(result['items'])} missing items."
        await on_audio(b"\x30\x40" * 240)
        return VoiceTurnResult("What have I missed?", response)


def test_backend_checklist_tool_executes_locally() -> None:
    pipeline = ChecklistVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
    ):
        authenticate_and_start(websocket)
        establish_connected_state(websocket)

        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"

        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )
        assert receive_control(websocket).payload["text"] == "What have I missed?"
        response = receive_control(websocket)
        assert response.payload["text"].startswith("Found ")


MC_IDENTITY = ControlIdentity("FA-18C_hornet", "MASTER_CAUTION_LT", "integer", 0)
MC_ENTRY = CatalogEntry(MC_IDENTITY, "Master caution light", integer_max=1)


def establish_connected_state_with_master_caution(
    websocket, epoch: str, value: int
) -> None:
    websocket.send_text(
        TelemetryCatalog(epoch, 0, "FA-18C_hornet", 0, 1, [MC_ENTRY])
        .to_control()
        .to_json()
    )
    websocket.send_text(
        TelemetrySnapshot(
            epoch, 1, "FA-18C_hornet", 0, 1, [DecodedValue(MC_IDENTITY, True, value)]
        )
        .to_control()
        .to_json()
    )
    assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
        MediaKind.AUDIO_OUTPUT
    )
    assert receive_control(websocket).payload["kind"] == "cockpit_welcome"


def test_backend_rule_violation_fires_proactive_tts() -> None:
    pipeline = FakeVoicePipeline()
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
        establish_connected_state_with_master_caution(websocket, epoch, 1)

        time.sleep(0.35)
        websocket.send_text(
            TelemetryDelta(
                epoch, 2, "FA-18C_hornet", 0, 1, [DecodedValue(MC_IDENTITY, True, 1)]
            )
            .to_control()
            .to_json()
        )

        output = MediaPacket.from_bytes(websocket.receive_bytes())
        response = receive_control(websocket)

    assert output.kind is MediaKind.AUDIO_OUTPUT
    assert response.payload["proactive"] is True
    assert "Master Caution" in response.payload["text"]
    assert len(pipeline.announcements) == 2


def test_proactive_announcement_suppressed_during_ptt() -> None:
    pipeline = FakeVoicePipeline()
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
        establish_connected_state_with_master_caution(websocket, epoch, 1)

        websocket.send_text(ControlMessage("ptt.start").to_json())
        time.sleep(0.35)
        websocket.send_text(
            TelemetryDelta(
                epoch, 2, "FA-18C_hornet", 0, 1, [DecodedValue(MC_IDENTITY, True, 1)]
            )
            .to_control()
            .to_json()
        )
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert len(pipeline.announcements) == 1


class BlockingAfterWelcomeVoicePipeline(FakeVoicePipeline):
    """Welcome completes normally; subsequent announcements block until interrupted."""

    def __init__(self) -> None:
        super().__init__(block=False)
        self._announce_count = 0
        self._blocking_release = asyncio.Event()

    async def announce(self, announcement, on_audio) -> str:
        self._announce_count += 1
        self.announcements.append(announcement)
        await on_audio(b"\x50\x60" * 240)
        if self._announce_count > 1:
            await self._blocking_release.wait()
        return announcement.text

    async def interrupt(self) -> None:
        self.interrupt_calls += 1
        self._blocking_release.set()


def test_proactive_event_resolution_interrupts_in_progress_speech() -> None:
    pipeline = BlockingAfterWelcomeVoicePipeline()
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
        establish_connected_state_with_master_caution(websocket, epoch, 1)

        time.sleep(0.35)
        websocket.send_text(
            TelemetryDelta(
                epoch, 2, "FA-18C_hornet", 0, 1, [DecodedValue(MC_IDENTITY, True, 1)]
            )
            .to_control()
            .to_json()
        )
        assert MediaPacket.from_bytes(websocket.receive_bytes()).kind is (
            MediaKind.AUDIO_OUTPUT
        )

        time.sleep(0.55)
        websocket.send_text(
            TelemetryDelta(
                epoch, 3, "FA-18C_hornet", 0, 1, [DecodedValue(MC_IDENTITY, True, 0)]
            )
            .to_control()
            .to_json()
        )
        websocket.send_text(ControlMessage("future.message").to_json())
        assert receive_control(websocket).payload["code"] == "unsupported_message"

    assert pipeline.interrupt_calls >= 1
