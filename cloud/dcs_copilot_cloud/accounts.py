"""Bounded cloud account tools and semantic flight-session persistence."""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select

from .database import (
    AircraftPreference,
    Database,
    FlightSessionRecord,
    PilotMemory,
    utc_now,
)

ACCOUNT_TOOL_VERSION = 1
MEMORY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CHATTER_LEVELS = frozenset({"minimal", "normal", "coach"})
LOGGER = logging.getLogger(__name__)


class AccountToolName(StrEnum):
    GET_PILOT_MEMORIES = "get_pilot_memories"
    REMEMBER_PILOT_FACT = "remember_pilot_fact"
    FORGET_PILOT_FACT = "forget_pilot_fact"
    GET_AIRCRAFT_PREFERENCES = "get_aircraft_preferences"
    SET_CHATTER_LEVEL = "set_chatter_level"
    GET_FLIGHT_HISTORY = "get_flight_history"


ACCOUNT_TOOL_NAMES = tuple(item.value for item in AccountToolName)


class AccountToolError(ValueError):
    pass


class AccountToolExecutor:
    """Executes only allowlisted cloud account tools for one authenticated user."""

    def __init__(self, store: AccountStore, user_id: str | None) -> None:
        self._store = store
        self._user_id = user_id

    async def request(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._user_id is None:
            return account_tool_error(
                "account_authentication_required",
                "cloud account tools require a signed user access token",
            )
        try:
            name = AccountToolName(tool)
            if name is AccountToolName.GET_PILOT_MEMORIES:
                aircraft, key, limit = validate_memory_query(arguments)
                memories = await self._store.get_memories(
                    self._user_id, aircraft=aircraft, key=key, limit=limit
                )
                return account_tool_result(memories=memories)
            if name is AccountToolName.REMEMBER_PILOT_FACT:
                aircraft, key, value = validate_remember(arguments)
                memory = await self._store.remember(
                    self._user_id, aircraft=aircraft, key=key, value=value
                )
                return account_tool_result(memory=memory)
            if name is AccountToolName.FORGET_PILOT_FACT:
                aircraft, key = validate_forget(arguments)
                forgotten = await self._store.forget(
                    self._user_id, aircraft=aircraft, key=key
                )
                return account_tool_result(forgotten=forgotten)
            if name is AccountToolName.GET_AIRCRAFT_PREFERENCES:
                aircraft = validate_preference_query(arguments)
                preferences = await self._store.get_preferences(
                    self._user_id, aircraft=aircraft
                )
                return account_tool_result(preferences=preferences)
            if name is AccountToolName.SET_CHATTER_LEVEL:
                aircraft, level = validate_chatter(arguments)
                preference = await self._store.set_preference(
                    self._user_id,
                    aircraft=aircraft,
                    key="chatter_level",
                    value=level,
                )
                return account_tool_result(preference=preference)
            aircraft, limit = validate_history_query(arguments)
            flights = await self._store.get_flight_history(
                self._user_id, aircraft=aircraft, limit=limit
            )
            return account_tool_result(flights=flights)
        except (ValueError, AccountToolError) as exc:
            return account_tool_error("invalid_account_tool", str(exc))
        except Exception:
            LOGGER.exception("cloud account tool failed: %s", tool)
            return account_tool_error(
                "account_tool_failed", "cloud account storage is unavailable"
            )


class AccountStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def remember(
        self,
        user_id: str,
        *,
        aircraft: str | None,
        key: str,
        value: str | float | bool,
    ) -> dict[str, Any]:
        aircraft_key = aircraft or ""
        encoded = json.dumps(value, separators=(",", ":"))
        now = utc_now()
        async with self.database.session() as session:
            memory = await session.scalar(
                select(PilotMemory).where(
                    PilotMemory.user_id == user_id,
                    PilotMemory.aircraft == aircraft_key,
                    PilotMemory.key == key,
                )
            )
            if memory is None:
                memory = PilotMemory(
                    id=str(uuid4()),
                    user_id=user_id,
                    aircraft=aircraft_key,
                    key=key,
                    value_json=encoded,
                    created_at=now,
                    updated_at=now,
                )
                session.add(memory)
            else:
                memory.value_json = encoded
                memory.updated_at = now
            await session.commit()
            return serialize_memory(memory)

    async def get_memories(
        self,
        user_id: str,
        *,
        aircraft: str | None,
        key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        query: Select[tuple[PilotMemory]] = select(PilotMemory).where(
            PilotMemory.user_id == user_id
        )
        if aircraft is not None:
            query = query.where(PilotMemory.aircraft == aircraft)
        if key is not None:
            query = query.where(PilotMemory.key == key)
        query = query.order_by(PilotMemory.updated_at.desc()).limit(limit)
        async with self.database.session() as session:
            memories = (await session.scalars(query)).all()
            return [serialize_memory(memory) for memory in memories]

    async def forget(self, user_id: str, *, aircraft: str | None, key: str) -> bool:
        async with self.database.session() as session:
            memory = await session.scalar(
                select(PilotMemory).where(
                    PilotMemory.user_id == user_id,
                    PilotMemory.aircraft == (aircraft or ""),
                    PilotMemory.key == key,
                )
            )
            if memory is None:
                return False
            await session.delete(memory)
            await session.commit()
            return True

    async def set_preference(
        self,
        user_id: str,
        *,
        aircraft: str | None,
        key: str,
        value: str | float | bool,
    ) -> dict[str, Any]:
        aircraft_key = aircraft or ""
        encoded = json.dumps(value, separators=(",", ":"))
        now = utc_now()
        async with self.database.session() as session:
            preference = await session.scalar(
                select(AircraftPreference).where(
                    AircraftPreference.user_id == user_id,
                    AircraftPreference.aircraft == aircraft_key,
                    AircraftPreference.key == key,
                )
            )
            if preference is None:
                preference = AircraftPreference(
                    id=str(uuid4()),
                    user_id=user_id,
                    aircraft=aircraft_key,
                    key=key,
                    value_json=encoded,
                    updated_at=now,
                )
                session.add(preference)
            else:
                preference.value_json = encoded
                preference.updated_at = now
            await session.commit()
            return serialize_preference(preference)

    async def get_preferences(
        self, user_id: str, *, aircraft: str | None
    ) -> list[dict[str, Any]]:
        query: Select[tuple[AircraftPreference]] = select(AircraftPreference).where(
            AircraftPreference.user_id == user_id
        )
        if aircraft is not None:
            query = query.where(AircraftPreference.aircraft == aircraft)
        query = query.order_by(AircraftPreference.key)
        async with self.database.session() as session:
            preferences = (await session.scalars(query)).all()
            return [serialize_preference(preference) for preference in preferences]

    async def start_flight(
        self,
        user_id: str,
        *,
        client_session_id: str,
        device_id: str,
        aircraft: str | None = None,
    ) -> None:
        aircraft = canonical_aircraft_name(aircraft) if aircraft is not None else None
        async with self.database.session() as session:
            record = await session.scalar(
                select(FlightSessionRecord).where(
                    FlightSessionRecord.user_id == user_id,
                    FlightSessionRecord.client_session_id == client_session_id,
                )
            )
            if record is None:
                session.add(
                    FlightSessionRecord(
                        id=str(uuid4()),
                        user_id=user_id,
                        client_session_id=client_session_id,
                        device_id=device_id,
                        aircraft=aircraft,
                    )
                )
            else:
                record.device_id = device_id
                record.aircraft = aircraft or record.aircraft
                record.ended_at = None
            await session.commit()

    async def update_flight_aircraft(
        self, user_id: str, *, client_session_id: str, aircraft: str | None
    ) -> None:
        aircraft = canonical_aircraft_name(aircraft) if aircraft is not None else None
        async with self.database.session() as session:
            record = await session.scalar(
                select(FlightSessionRecord).where(
                    FlightSessionRecord.user_id == user_id,
                    FlightSessionRecord.client_session_id == client_session_id,
                )
            )
            if record is not None:
                record.aircraft = aircraft
                await session.commit()

    async def end_flight(self, user_id: str, *, client_session_id: str) -> None:
        async with self.database.session() as session:
            record = await session.scalar(
                select(FlightSessionRecord).where(
                    FlightSessionRecord.user_id == user_id,
                    FlightSessionRecord.client_session_id == client_session_id,
                )
            )
            if record is not None and record.ended_at is None:
                record.ended_at = utc_now()
                await session.commit()

    async def get_flight_history(
        self, user_id: str, *, aircraft: str | None, limit: int
    ) -> list[dict[str, Any]]:
        query: Select[tuple[FlightSessionRecord]] = select(FlightSessionRecord).where(
            FlightSessionRecord.user_id == user_id
        )
        if aircraft is not None:
            query = query.where(FlightSessionRecord.aircraft == aircraft)
        query = query.order_by(FlightSessionRecord.started_at.desc()).limit(limit)
        async with self.database.session() as session:
            records = (await session.scalars(query)).all()
            return [serialize_flight(record) for record in records]


def validate_memory_query(
    arguments: dict[str, Any],
) -> tuple[str | None, str | None, int]:
    require_keys(arguments, {"aircraft", "key", "limit"})
    aircraft = optional_aircraft(arguments.get("aircraft"))
    key_value = arguments.get("key")
    key = validate_key(key_value) if key_value is not None else None
    limit = bounded_int(arguments.get("limit", 10), minimum=1, maximum=20)
    return aircraft, key, limit


def validate_remember(
    arguments: dict[str, Any],
) -> tuple[str | None, str, str | int | float | bool]:
    require_keys(arguments, {"aircraft", "key", "value"}, required={"key", "value"})
    aircraft = optional_aircraft(arguments.get("aircraft"))
    key = validate_key(arguments["key"])
    value = arguments["value"]
    if isinstance(value, str):
        value = value.strip()
        if not value or len(value) > 512:
            raise AccountToolError("memory value must contain 1 to 512 characters")
    elif not isinstance(value, (int, float, bool)) or isinstance(value, complex):
        raise AccountToolError("memory value must be a string, number, or boolean")
    elif (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (
            abs(value) > 1_000_000_000_000
            or (isinstance(value, float) and not math.isfinite(value))
        )
    ):
        raise AccountToolError("numeric memory value is outside the allowed range")
    return aircraft, key, value


def validate_forget(arguments: dict[str, Any]) -> tuple[str | None, str]:
    require_keys(arguments, {"aircraft", "key"}, required={"key"})
    return optional_aircraft(arguments.get("aircraft")), validate_key(arguments["key"])


def validate_chatter(arguments: dict[str, Any]) -> tuple[str | None, str]:
    require_keys(arguments, {"aircraft", "level"}, required={"level"})
    level = arguments["level"]
    if not isinstance(level, str) or level.lower() not in CHATTER_LEVELS:
        raise AccountToolError("chatter level must be minimal, normal, or coach")
    return optional_aircraft(arguments.get("aircraft")), level.lower()


def validate_preference_query(arguments: dict[str, Any]) -> str | None:
    require_keys(arguments, {"aircraft"})
    return optional_aircraft(arguments.get("aircraft"))


def validate_history_query(arguments: dict[str, Any]) -> tuple[str | None, int]:
    require_keys(arguments, {"aircraft", "limit"})
    return (
        optional_aircraft(arguments.get("aircraft")),
        bounded_int(arguments.get("limit", 5), minimum=1, maximum=20),
    )


def require_keys(
    arguments: dict[str, Any], allowed: set[str], *, required: set[str] | None = None
) -> None:
    if not isinstance(arguments, dict):
        raise AccountToolError("tool arguments must be an object")
    unknown = set(arguments) - allowed
    if unknown:
        raise AccountToolError(
            f"unexpected tool arguments: {', '.join(sorted(unknown))}"
        )
    missing = (required or set()) - set(arguments)
    if missing:
        raise AccountToolError(f"missing tool arguments: {', '.join(sorted(missing))}")


def optional_aircraft(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AccountToolError("aircraft must be a string")
    aircraft = value.strip()
    if not aircraft or len(aircraft) > 64:
        raise AccountToolError("aircraft must contain 1 to 64 characters")
    return canonical_aircraft_name(aircraft)


def canonical_aircraft_name(aircraft: str) -> str:
    if aircraft.lower().replace("_", "-") in {
        "hornet",
        "fa-18c",
        "f/a-18c",
        "fa-18c-hornet",
    }:
        return "F/A-18C"
    return aircraft


def validate_key(value: Any) -> str:
    if not isinstance(value, str) or not MEMORY_KEY_PATTERN.fullmatch(value):
        raise AccountToolError(
            "memory key must be lowercase snake_case and at most 64 characters"
        )
    return value


def bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AccountToolError("limit must be an integer")
    if not minimum <= value <= maximum:
        raise AccountToolError(f"limit must be between {minimum} and {maximum}")
    return value


def account_tool_result(**payload: Any) -> dict[str, Any]:
    return {"available": True, "tool_version": ACCOUNT_TOOL_VERSION, **payload}


def account_tool_error(code: str, detail: str) -> dict[str, Any]:
    return {
        "available": False,
        "tool_version": ACCOUNT_TOOL_VERSION,
        "error": {"code": code, "detail": detail},
    }


def serialize_memory(memory: PilotMemory) -> dict[str, Any]:
    return {
        "memory_id": memory.id,
        "aircraft": memory.aircraft or None,
        "key": memory.key,
        "value": json.loads(memory.value_json),
        "updated_at": isoformat(memory.updated_at),
    }


def serialize_preference(preference: AircraftPreference) -> dict[str, Any]:
    return {
        "aircraft": preference.aircraft or None,
        "key": preference.key,
        "value": json.loads(preference.value_json),
        "updated_at": isoformat(preference.updated_at),
    }


def serialize_flight(record: FlightSessionRecord) -> dict[str, Any]:
    started = as_utc(record.started_at)
    ended = as_utc(record.ended_at) if record.ended_at is not None else None
    return {
        "flight_id": record.id,
        "aircraft": record.aircraft,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat() if ended is not None else None,
        "duration_seconds": max(0, round((ended - started).total_seconds()))
        if ended is not None
        else None,
    }


def isoformat(value: datetime) -> str:
    return as_utc(value).isoformat()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
