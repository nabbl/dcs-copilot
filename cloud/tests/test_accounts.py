from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dcs_copilot_cloud.accounts import AccountStore, AccountToolExecutor
from dcs_copilot_cloud.auth import AuthService
from dcs_copilot_cloud.database import Database, normalize_database_url

SIGNING_KEY = "test-signing-key-that-is-at-least-32-bytes"


def test_database_urls_support_postgresql_and_sqlite_only() -> None:
    assert normalize_database_url("postgres://db/app") == (
        "postgresql+asyncpg://db/app"
    )
    assert normalize_database_url("sqlite:///local.db") == (
        "sqlite+aiosqlite:///local.db"
    )
    with pytest.raises(ValueError, match="PostgreSQL or SQLite"):
        normalize_database_url("mysql://db/app")


def test_memories_are_bounded_typed_persistent_and_user_isolated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"
        database = Database(database_url)
        await database.initialize()
        auth = AuthService(database, signing_key=SIGNING_KEY)
        user_id, _ = await auth.register(
            "pilot@example.com", "correct-horse-battery-staple", "pc-1"
        )
        other_user_id, _ = await auth.register(
            "wingman@example.com", "correct-horse-battery-staple", "pc-2"
        )
        tools = AccountToolExecutor(AccountStore(database), user_id)
        saved = await tools.request(
            "remember_pilot_fact",
            {"aircraft": "Hornet", "key": "bingo_fuel", "value": 3500},
        )
        assert saved["available"] is True
        assert saved["memory"]["aircraft"] == "F/A-18C"
        assert saved["memory"]["value"] == 3500
        updated = await tools.request(
            "remember_pilot_fact",
            {"aircraft": "F/A-18C", "key": "bingo_fuel", "value": 3200},
        )
        assert updated["memory"]["memory_id"] == saved["memory"]["memory_id"]

        recalled = await tools.request(
            "get_pilot_memories",
            {"aircraft": "F/A-18C", "key": "bingo_fuel", "limit": 1},
        )
        assert recalled["memories"][0]["value"] == 3200
        isolated = await AccountToolExecutor(
            AccountStore(database), other_user_id
        ).request("get_pilot_memories", {"limit": 20})
        assert isolated["memories"] == []
        invalid = await tools.request(
            "remember_pilot_fact",
            {"aircraft": "F/A-18C", "key": "Bingo Fuel", "value": 3500},
        )
        assert invalid["available"] is False
        assert invalid["error"]["code"] == "invalid_account_tool"
        await database.close()

        reopened = Database(database_url)
        await reopened.initialize()
        persisted = await AccountToolExecutor(AccountStore(reopened), user_id).request(
            "get_pilot_memories",
            {"aircraft": "F/A-18C", "key": "bingo_fuel"},
        )
        assert persisted["memories"][0]["value"] == 3200
        await reopened.close()

    asyncio.run(scenario())


def test_preferences_flight_history_and_unauthenticated_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = Database(f"sqlite+aiosqlite:///{tmp_path / 'flights.db'}")
        await database.initialize()
        auth = AuthService(database, signing_key=SIGNING_KEY)
        user_id, _ = await auth.register(
            "pilot@example.com", "correct-horse-battery-staple", "pc-1"
        )
        store = AccountStore(database)
        tools = AccountToolExecutor(store, user_id)
        preference = await tools.request(
            "set_chatter_level", {"aircraft": "F/A-18C", "level": "minimal"}
        )
        assert preference["preference"]["value"] == "minimal"
        recalled_preference = await tools.request(
            "get_aircraft_preferences", {"aircraft": "F/A-18C"}
        )
        assert recalled_preference["preferences"] == [preference["preference"]]

        await store.start_flight(
            user_id,
            client_session_id="flight-1",
            device_id="pc-1",
        )
        await store.update_flight_aircraft(
            user_id, client_session_id="flight-1", aircraft="F/A-18C"
        )
        await store.end_flight(user_id, client_session_id="flight-1")
        history = await tools.request(
            "get_flight_history", {"aircraft": "F/A-18C", "limit": 5}
        )
        assert len(history["flights"]) == 1
        assert history["flights"][0]["aircraft"] == "F/A-18C"
        assert set(history["flights"][0]) == {
            "flight_id",
            "aircraft",
            "started_at",
            "ended_at",
            "duration_seconds",
        }

        unavailable = await AccountToolExecutor(store, None).request(
            "get_pilot_memories", {}
        )
        assert unavailable["available"] is False
        assert unavailable["error"]["code"] == "account_authentication_required"
        await database.close()

    asyncio.run(scenario())
