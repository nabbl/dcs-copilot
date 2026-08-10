from __future__ import annotations

import asyncio
from pathlib import Path

from dcs_copilot_cloud.accounts import AccountStore
from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.database import Database
from dcs_copilot_protocol import AircraftChanged, AudioFormat, ControlMessage
from fastapi.testclient import TestClient

SIGNING_KEY = "test-signing-key-that-is-at-least-32-bytes"


def settings(database: Path) -> CloudSettings:
    return CloudSettings(
        dev_access_token="",
        database_url=f"sqlite+aiosqlite:///{database}",
        auth_signing_key=SIGNING_KEY,
    )


def test_register_login_refresh_rotation_and_bearer_identity(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path / "accounts.db"))
    credentials = {
        "email": "Pilot@Example.com",
        "password": "correct-horse-battery-staple",
        "device_id": "gaming-pc",
    }
    with TestClient(app) as client:
        registered = client.post("/v1/auth/register", json=credentials)
        assert registered.status_code == 201
        first = registered.json()
        assert first["token_type"] == "bearer"
        assert first["expires_in"] == 900
        assert client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        ).json() == {"user_id": first["user_id"], "device_id": "gaming-pc"}

        duplicate = client.post("/v1/auth/register", json=credentials)
        assert duplicate.status_code == 409
        failed = client.post(
            "/v1/auth/token", json={**credentials, "password": "wrong-password"}
        )
        assert failed.status_code == 401
        assert failed.json()["detail"] == "invalid email or password"

        refreshed = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": first["refresh_token"],
                "device_id": "gaming-pc",
            },
        )
        assert refreshed.status_code == 200
        second = refreshed.json()
        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        replay = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": first["refresh_token"],
                "device_id": "gaming-pc",
            },
        )
        assert replay.status_code == 401

        logged_out = client.post(
            "/v1/auth/logout",
            json={"refresh_token": second["refresh_token"]},
            headers={"Authorization": f"Bearer {second['access_token']}"},
        )
        assert logged_out.status_code == 204
        revoked = client.post(
            "/v1/auth/refresh",
            json={
                "refresh_token": second["refresh_token"],
                "device_id": "gaming-pc",
            },
        )
        assert revoked.status_code == 401

        logged_in = client.post("/v1/auth/token", json=credentials)
        assert logged_in.status_code == 200
        assert logged_in.json()["user_id"] == first["user_id"]


def test_realtime_access_token_is_signed_and_device_bound(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path / "realtime-auth.db"))
    with TestClient(app) as client:
        account = client.post(
            "/v1/auth/register",
            json={
                "email": "pilot@example.com",
                "password": "correct-horse-battery-staple",
                "device_id": "device-1",
            },
        ).json()
        with client.websocket_connect("/v1/realtime") as websocket:
            assert ControlMessage.from_json(websocket.receive_text()).type == "hello"
            websocket.send_text(
                ControlMessage(
                    "authenticate",
                    {
                        "access_token": account["access_token"],
                        "device_id": "other-device",
                    },
                ).to_json()
            )
            error = ControlMessage.from_json(websocket.receive_text())
            assert error.payload["code"] == "authentication_failed"

        token = account["access_token"]
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with client.websocket_connect("/v1/realtime") as websocket:
            assert ControlMessage.from_json(websocket.receive_text()).type == "hello"
            websocket.send_text(
                ControlMessage(
                    "authenticate",
                    {"access_token": tampered, "device_id": "device-1"},
                ).to_json()
            )
            error = ControlMessage.from_json(websocket.receive_text())
            assert error.payload["code"] == "authentication_failed"


def test_authenticated_flight_session_closes_on_disconnect(tmp_path: Path) -> None:
    database_path = tmp_path / "flight-disconnect.db"
    app = create_app(settings(database_path))
    with TestClient(app) as client:
        account = client.post(
            "/v1/auth/register",
            json={
                "email": "pilot@example.com",
                "password": "correct-horse-battery-staple",
                "device_id": "device-1",
            },
        ).json()
        with client.websocket_connect("/v1/realtime") as websocket:
            assert ControlMessage.from_json(websocket.receive_text()).type == "hello"
            websocket.send_text(
                ControlMessage(
                    "authenticate",
                    {
                        "access_token": account["access_token"],
                        "device_id": "device-1",
                    },
                ).to_json()
            )
            assert ControlMessage.from_json(websocket.receive_text()).payload[
                "authenticated"
            ]
            websocket.send_text(
                ControlMessage(
                    "session.start",
                    {"session_id": "flight-1", "audio": AudioFormat().to_dict()},
                ).to_json()
            )
            assert ControlMessage.from_json(websocket.receive_text()).payload[
                "session_active"
            ]
            websocket.send_text(AircraftChanged("Hornet").to_control().to_json())
            websocket.send_text(ControlMessage("barrier").to_json())
            assert ControlMessage.from_json(websocket.receive_text()).payload[
                "code"
            ] == "unsupported_message"

    async def verify() -> None:
        database = Database(f"sqlite+aiosqlite:///{database_path}")
        await database.initialize()
        flights = await AccountStore(database).get_flight_history(
            account["user_id"], aircraft=None, limit=5
        )
        assert len(flights) == 1
        assert flights[0]["aircraft"] == "F/A-18C"
        assert flights[0]["ended_at"] is not None
        await database.close()

    asyncio.run(verify())
