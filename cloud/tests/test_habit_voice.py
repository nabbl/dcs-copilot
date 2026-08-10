from __future__ import annotations

from pathlib import Path

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.voice import VoiceTurnResult
from dcs_copilot_protocol import (
    AircraftChanged,
    AudioFormat,
    ControlMessage,
    FlightSummary,
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
            {"session_id": session_id, "audio": AudioFormat().to_dict()},
        ).to_json()
    )
    assert receive_control(websocket).payload["session_active"] is True
    websocket.send_text(AircraftChanged("F/A-18C").to_control().to_json())


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
        with client.websocket_connect("/v1/realtime") as websocket:
            start(websocket, account["access_token"], "flight-upload")
            for index in range(1, 6):
                summary = FlightSummary(
                    f"20000000-0000-4000-8000-{index:012d}",
                    "FA-18C_hornet",
                    {"FA18_REFUELING_PROBE_LEFT_OUT": int(index <= 3)},
                )
                request = summary.to_control()
                websocket.send_text(request.to_json())
                accepted = receive_control(websocket)
                assert accepted.correlation_id == request.message_id
                assert accepted.payload == {
                    "event_type": "flight.summary.accepted",
                    "summary_id": summary.summary_id,
                    "duplicate": False,
                }
                if index == 1:
                    duplicate_request = summary.to_control()
                    websocket.send_text(duplicate_request.to_json())
                    duplicate = receive_control(websocket)
                    assert duplicate.correlation_id == duplicate_request.message_id
                    assert duplicate.payload["duplicate"] is True

    pipeline = HabitVoicePipeline()
    restarted_app = create_app(
        settings, voice_pipeline_factory=lambda _settings: pipeline
    )
    with TestClient(restarted_app) as client:
        account = client.post("/v1/auth/token", json=credentials).json()
        with client.websocket_connect("/v1/realtime") as websocket:
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
            assert receive_control(websocket).payload["text"] == (
                "You've left the refueling probe out in three of your last five "
                "Hornet flights."
            )
    assert pipeline.closed


def test_dev_token_cannot_upload_account_flight_statistics() -> None:
    app = create_app(CloudSettings(dev_access_token="test-token"))
    with (
        TestClient(app) as client,
        client.websocket_connect("/v1/realtime") as websocket,
    ):
        start(websocket, "test-token", "dev-flight")
        request = FlightSummary(
            "30000000-0000-4000-8000-000000000001",
            "F/A-18C",
            {"FA18_MASTER_CAUTION": 1},
        ).to_control()
        websocket.send_text(request.to_json())
        error = receive_control(websocket)
        assert error.correlation_id == request.message_id
        assert error.payload["code"] == "account_authentication_required"
