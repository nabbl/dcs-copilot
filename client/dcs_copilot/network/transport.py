"""Replaceable realtime transport boundary; WebSocket is the v1 adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Protocol, Self

from websockets.asyncio.client import ClientConnection, connect


class RealtimeTransport(Protocol):
    async def send_text(self, payload: str) -> None: ...

    async def send_bytes(self, payload: bytes) -> None: ...

    async def receive(self) -> str | bytes: ...

    async def close(self) -> None: ...


class WebSocketTransport:
    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    async def send_text(self, payload: str) -> None:
        await self._connection.send(payload)

    async def send_bytes(self, payload: bytes) -> None:
        await self._connection.send(payload)

    async def receive(self) -> str | bytes:
        return await self._connection.recv(decode=None)

    async def close(self) -> None:
        await self._connection.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.close()


@asynccontextmanager
async def open_websocket_transport(url: str) -> AsyncIterator[RealtimeTransport]:
    async with connect(
        url,
        compression=None,
        open_timeout=5,
        close_timeout=2,
        ping_interval=20,
        ping_timeout=20,
        max_size=2 * 1024 * 1024,
        max_queue=16,
    ) as connection:
        yield WebSocketTransport(connection)
