from __future__ import annotations

from dataclasses import dataclass

import pytest
from dcs_copilot.desktop.auth import (
    AuthError,
    StoredAuthSession,
    TokenPair,
    auth_base_url,
)


@dataclass
class MemoryStore:
    value: str | None = None

    def get(self, _device_id: str) -> str | None:
        return self.value

    def set(self, _device_id: str, refresh_token: str) -> None:
        self.value = refresh_token

    def delete(self, _device_id: str) -> None:
        self.value = None


class FakeClient:
    def __init__(self) -> None:
        self.refreshed: list[str] = []

    def refresh(self, token: str, device_id: str) -> TokenPair:
        self.refreshed.append(f"{token}:{device_id}")
        return TokenPair("new-access", "new-refresh", 900)


def test_auth_base_url_tracks_realtime_origin_and_tls() -> None:
    assert (
        auth_base_url("wss://api.example/v1/realtime") == "https://api.example/v1/auth"
    )
    assert (
        auth_base_url("ws://localhost:8000/v1/realtime")
        == "http://localhost:8000/v1/auth"
    )
    with pytest.raises(AuthError, match="ws://"):
        auth_base_url("https://api.example/v1/realtime")
    with pytest.raises(AuthError, match="localhost"):
        auth_base_url("ws://api.example/v1/realtime")


def test_stored_session_rotates_refresh_token() -> None:
    store = MemoryStore("old-refresh")
    session = StoredAuthSession("ws://localhost/v1/realtime", "pc-1", store)
    fake = FakeClient()
    session.client = fake  # type: ignore[assignment]
    pair = session.restore()
    assert pair is not None
    assert pair.access_token == "new-access"
    assert store.value == "new-refresh"
    assert fake.refreshed == ["old-refresh:pc-1"]
