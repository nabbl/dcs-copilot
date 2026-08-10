from __future__ import annotations

from pathlib import Path

from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.voice import VoiceTurnResult
from dcs_copilot_protocol import (
    AircraftChanged,
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
)
from fastapi.testclient import TestClient

SIGNING_KEY = "test-signing-key-that-is-at-least-32-bytes"


class MemoryVoicePipeline:
    def __init__(self, *, recall_only: bool = False) -> None:
        self.recall_only = recall_only
        self.turns = 0
        self.closed = False

    async def respond(self, turn, on_audio, request_tool=None) -> VoiceTurnResult:
        assert request_tool is not None
        self.turns += 1
        if not self.recall_only and self.turns == 1:
            result = await request_tool(
                "remember_pilot_fact",
                {"aircraft": "F/A-18C", "key": "bingo_fuel", "value": 3500},
            )
            assert result["available"] is True
            response = "Hornet Bingo set to 3,500."
            transcript = "Remember Hornet Bingo is 3500."
        else:
            result = await request_tool(
                "get_pilot_memories",
                {"aircraft": "F/A-18C", "key": "bingo_fuel", "limit": 1},
            )
            response = f"Your Hornet Bingo is {result['memories'][0]['value']:,}."
            transcript = "What's my Bingo?"
        await on_audio(b"\x22\x33" * 240)
        return VoiceTurnResult(transcript, response)

    async def announce(self, announcement, on_audio) -> str:
        await on_audio(b"\x22\x33" * 240)
        return announcement.text

    async def interrupt(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


def receive_control(websocket) -> ControlMessage:
    return ControlMessage.from_json(websocket.receive_text())


def authenticate_and_start(websocket, access_token: str, session_id: str) -> None:
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


def voice_turn(websocket) -> str:
    websocket.send_text(ControlMessage("ptt.start").to_json())
    websocket.send_bytes(
        MediaPacket(MediaKind.AUDIO_INPUT, 0, 1, b"\x01\x02" * 320).to_bytes()
    )
    websocket.send_text(ControlMessage("ptt.end").to_json())
    assert receive_control(websocket).payload["event_type"] == "utterance.received"
    assert (
        MediaPacket.from_bytes(websocket.receive_bytes()).kind is MediaKind.AUDIO_OUTPUT
    )
    return receive_control(websocket).payload["text"]


def end_session(websocket, session_id: str) -> None:
    websocket.send_text(
        ControlMessage("session.end", {"session_id": session_id}).to_json()
    )
    assert receive_control(websocket).payload["session_active"] is False


def test_voice_memory_survives_complete_cloud_restart(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'memory-round-trip.db'}"
    settings = CloudSettings(
        dev_access_token="",
        database_url=database_url,
        auth_signing_key=SIGNING_KEY,
    )
    first_pipeline = MemoryVoicePipeline()
    first_app = create_app(
        settings, voice_pipeline_factory=lambda _settings: first_pipeline
    )
    credentials = {
        "email": "pilot@example.com",
        "password": "correct-horse-battery-staple",
        "device_id": "gaming-pc",
    }
    with TestClient(first_app) as client:
        account = client.post("/v1/auth/register", json=credentials).json()
        with client.websocket_connect("/v1/realtime") as websocket:
            authenticate_and_start(websocket, account["access_token"], "flight-1")
            assert voice_turn(websocket) == "Hornet Bingo set to 3,500."
            assert voice_turn(websocket) == "Your Hornet Bingo is 3,500."
            end_session(websocket, "flight-1")
    assert first_pipeline.closed

    second_pipeline = MemoryVoicePipeline(recall_only=True)
    restarted_app = create_app(
        settings, voice_pipeline_factory=lambda _settings: second_pipeline
    )
    with TestClient(restarted_app) as client:
        account = client.post("/v1/auth/token", json=credentials).json()
        with client.websocket_connect("/v1/realtime") as websocket:
            authenticate_and_start(websocket, account["access_token"], "flight-2")
            assert voice_turn(websocket) == "Your Hornet Bingo is 3,500."
            end_session(websocket, "flight-2")
    assert second_pipeline.closed
