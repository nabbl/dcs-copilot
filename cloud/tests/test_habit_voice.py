from __future__ import annotations

import asyncio
from pathlib import Path

from dcs_copilot_cloud.accounts import AccountStore
from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.auth import AuthService
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.database import Database
from dcs_copilot_cloud.habits.models import FlightSummary
from dcs_copilot_cloud.voice import VoiceTurnResult
from dcs_copilot_protocol import (
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
)
from fastapi.testclient import TestClient

SIGNING_KEY = "test-signing-key-that-is-at-least-32-bytes"


class HabitVoicePipeline:
    def __init__(self) -> None:
        self.closed = False

    async def respond(self, turn, on_audio, request_tool=None) -> VoiceTurnResult:
        assert request_tool is not None
        result = await request_tool(
            "get_pilot_habits",
            {
                "aircraft": "F/A-18C",
                "rule_id": "FA18_REFUELING_PROBE_LEFT_OUT",
                "window": 5,
            },
        )
        response = result["habits"][0]["statement"]
        await on_audio(b"\x44\x55" * 240)
        return VoiceTurnResult("What's my bad habit?", response)

    async def announce(self, announcement, on_audio) -> str:
        await on_audio(b"\x44\x55" * 240)
        return announcement.text

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def receive_control(websocket) -> ControlMessage:
    return ControlMessage.from_json(websocket.receive_text())


def start(websocket, access_token: str, session_id: str) -> None:
    assert receive_control(websocket).type == "hello"
    websocket.send_text(
        ControlMessage(
            "authenticate",
            {"access_token": access_token, "device_id": "gaming-pc"},
        ).to_json()
    )
    assert receive_control(websocket).payload["authenticated"] is True
    websocket.send_text(
        ControlMessage(
            "session.start",
            {
                "session_id": session_id,
                "input_audio": AudioFormat().to_dict(),
                "output_audio": AudioFormat(sample_rate=24_000).to_dict(),
            },
        ).to_json()
    )
    assert receive_control(websocket).payload["session_active"] is True


def test_semantic_summaries_survive_restart_and_drive_exact_voice_response(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'habit-round-trip.db'}"
    settings = CloudSettings(
        dev_access_token="",
        database_url=database_url,
        auth_signing_key=SIGNING_KEY,
    )
    credentials = {
        "email": "pilot@example.com",
        "password": "correct-horse-battery-staple",
        "device_id": "gaming-pc",
    }
    first_app = create_app(settings)
    with TestClient(first_app) as client:
        account = client.post("/v1/auth/register", json=credentials).json()
    user_id = account["user_id"]

    # Flight summaries are cloud-internal: ingest them directly against the
    # account store rather than over the client WebSocket (there is no
    # client ingest path in protocol v2).
    async def ingest_summaries() -> None:
        database = Database(database_url)
        await database.initialize()
        store = AccountStore(database)
        for index in range(1, 6):
            summary = FlightSummary(
                f"20000000-0000-4000-8000-{index:012d}",
                "FA-18C_hornet",
                {"FA18_REFUELING_PROBE_LEFT_OUT": int(index <= 3)},
            )
            accepted = await store.ingest_flight_summary(user_id, summary)
            assert accepted is True
            if index == 1:
                duplicate = await store.ingest_flight_summary(user_id, summary)
                assert duplicate is False
        await database.close()

    asyncio.run(ingest_summaries())

    pipeline = HabitVoicePipeline()
    restarted_app = create_app(
        settings, voice_pipeline_factory=lambda _settings: pipeline
    )
    with TestClient(restarted_app) as client:
        account = client.post("/v1/auth/token", json=credentials).json()
        with client.websocket_connect("/v2/realtime") as websocket:
            start(websocket, account["access_token"], "flight-recall")
            websocket.send_text(ControlMessage("ptt.start").to_json())
            websocket.send_bytes(
                MediaPacket(
                    MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320
                ).to_bytes()
            )
            websocket.send_text(ControlMessage("ptt.end").to_json())
            assert receive_control(websocket).payload["event_type"] == (
                "utterance.received"
            )
            assert MediaPacket.from_bytes(websocket.receive_bytes()).payload == (
                b"\x44\x55" * 240
            )
            assert receive_control(websocket).type == "pilot.text"
            response = receive_control(websocket)
            assert response.type == "assistant.text"
            assert response.payload["text"] == (
                "You've left the refueling probe out in three of your last five "
                "Hornet flights."
            )
    assert pipeline.closed


class AccountAuthRequiredVoicePipeline:
    def __init__(self) -> None:
        self.closed = False

    async def respond(self, turn, on_audio, request_tool=None) -> VoiceTurnResult:
        assert request_tool is not None
        result = await request_tool("get_pilot_habits", {"aircraft": "F/A-18C"})
        assert result["error"]["code"] == "account_authentication_required"
        await on_audio(b"\x44\x55" * 240)
        return VoiceTurnResult(
            "What's my bad habit?", "I can't check habits without an account."
        )

    async def announce(self, announcement, on_audio) -> str:
        await on_audio(b"\x44\x55" * 240)
        return announcement.text

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def test_dev_token_voice_session_account_tools_require_auth() -> None:
    pipeline = AccountAuthRequiredVoicePipeline()
    app = create_app(
        CloudSettings(dev_access_token="test-token"),
        voice_pipeline_factory=lambda _settings: pipeline,
    )
    with (
        TestClient(app) as client,
        client.websocket_connect("/v2/realtime") as websocket,
    ):
        start(websocket, "test-token", "dev-flight")
        websocket.send_text(ControlMessage("ptt.start").to_json())
        websocket.send_bytes(
            MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
        )
        websocket.send_text(ControlMessage("ptt.end").to_json())
        assert receive_control(websocket).payload["event_type"] == "utterance.received"
        assert MediaPacket.from_bytes(websocket.receive_bytes()).payload == (
            b"\x44\x55" * 240
        )
        assert receive_control(websocket).type == "pilot.text"
        response = receive_control(websocket)
        assert response.type == "assistant.text"
        assert response.payload["text"] == "I can't check habits without an account."
