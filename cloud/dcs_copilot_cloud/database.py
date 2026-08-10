"""Async account persistence shared by SQLite development and PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RefreshCredential(Base):
    __tablename__ = "refresh_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PilotMemory(Base):
    __tablename__ = "pilot_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "aircraft", "key", name="uq_pilot_memory"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    aircraft: Mapped[str] = mapped_column(String(64), default="")
    key: Mapped[str] = mapped_column(String(64))
    value_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AircraftPreference(Base):
    __tablename__ = "aircraft_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "aircraft", "key", name="uq_aircraft_preference"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    aircraft: Mapped[str] = mapped_column(String(64), default="")
    key: Mapped[str] = mapped_column(String(64))
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class FlightSessionRecord(Base):
    __tablename__ = "flight_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "client_session_id", name="uq_user_client_session"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_session_id: Mapped[str] = mapped_column(String(128))
    device_id: Mapped[str] = mapped_column(String(128))
    aircraft: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FlightSummaryRecord(Base):
    __tablename__ = "flight_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "summary_id", name="uq_user_flight_summary"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    summary_id: Mapped[str] = mapped_column(String(36))
    aircraft: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class FlightRuleStatistic(Base):
    __tablename__ = "flight_rule_statistics"
    __table_args__ = (
        UniqueConstraint(
            "flight_summary_id", "rule_id", name="uq_flight_summary_rule"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    flight_summary_id: Mapped[str] = mapped_column(
        ForeignKey("flight_summaries.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    activations: Mapped[int] = mapped_column(Integer)


class Database:
    """Owns the async engine without leaking SQLAlchemy into the client."""

    def __init__(self, url: str) -> None:
        normalized = normalize_database_url(url)
        options: dict[str, object] = {"pool_pre_ping": True}
        if normalized == "sqlite+aiosqlite:///:memory:":
            options["poolclass"] = StaticPool
        self.url = normalized
        self.engine: AsyncEngine = create_async_engine(normalized, **options)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self.sessions()
        try:
            yield session
        finally:
            cleanup = asyncio.create_task(
                session.close(), name="close-database-session"
            )
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise


def normalize_database_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("DCS_COPILOT_DATABASE_URL cannot be empty")
    if value.startswith("postgres://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
    if value.startswith("sqlite:///") and not value.startswith("sqlite+aiosqlite:///"):
        return "sqlite+aiosqlite:///" + value.removeprefix("sqlite:///")
    if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite:///")):
        raise ValueError("database URL must use PostgreSQL or SQLite")
    return value
