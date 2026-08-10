"""Correlation and lifecycle management for cloud-to-client aircraft tools."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from dcs_copilot_protocol import (
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    ControlMessage,
    ToolProtocolError,
)

ControlSender = Callable[[ControlMessage], Awaitable[None]]


class LocalAircraftToolError(RuntimeError):
    pass


class LocalAircraftToolTimeout(LocalAircraftToolError):
    pass


class LocalAircraftToolDisconnected(LocalAircraftToolError):
    pass


@dataclass(frozen=True, slots=True)
class _PendingTool:
    request: AircraftToolRequest
    future: asyncio.Future[AircraftToolResult]


class LocalAircraftToolBroker:
    """Sends validated requests and resolves only correlated tool results."""

    def __init__(self, send_control: ControlSender, *, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            raise ValueError("aircraft tool timeout must be greater than zero")
        self._send_control = send_control
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, _PendingTool] = {}
        self._closed = False

    async def request(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise LocalAircraftToolDisconnected("aircraft client disconnected")
        request = AircraftToolRequest.create(tool, arguments)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[AircraftToolResult] = loop.create_future()
        self._pending[request.request_id] = _PendingTool(request, future)
        try:
            await self._send_control(request.to_control())
            try:
                response = await asyncio.wait_for(
                    future,
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                raise LocalAircraftToolTimeout(
                    f"{request.tool.value} timed out waiting for the aircraft client"
                ) from exc
            if not response.ok:
                assert response.error is not None
                raise LocalAircraftToolError(
                    f"{response.error['code']}: {response.error['detail']}"
                )
            assert response.result is not None
            if request.tool is AircraftToolName.GET_AIRCRAFT_STATE:
                returned_fields = response.result["fields"]
                if set(returned_fields) != set(request.arguments["fields"]):
                    raise ToolProtocolError(
                        "aircraft state result fields do not match the request"
                    )
            if (
                request.tool is AircraftToolName.GET_RECENT_EVENTS
                and len(response.result["events"]) > request.arguments["limit"]
            ):
                raise ToolProtocolError("recent event result exceeds requested limit")
            return response.result
        finally:
            self._pending.pop(request.request_id, None)

    def resolve(self, message: ControlMessage) -> None:
        response = AircraftToolResult.from_control(message)
        pending = self._pending.get(response.request_id)
        if pending is None:
            raise ToolProtocolError("tool.result has no matching pending request")
        if response.tool != pending.request.tool.value:
            error = ToolProtocolError(
                "tool.result tool does not match the correlated request"
            )
            if not pending.future.done():
                pending.future.set_exception(error)
            raise error
        if not pending.future.done():
            pending.future.set_result(response)

    def disconnect(self) -> None:
        self._closed = True
        for pending in tuple(self._pending.values()):
            if not pending.future.done():
                pending.future.set_exception(
                    LocalAircraftToolDisconnected("aircraft client disconnected")
                )


def aircraft_tool_error_result(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, LocalAircraftToolTimeout):
        code = "aircraft_tool_timeout"
    elif isinstance(exc, LocalAircraftToolDisconnected):
        code = "aircraft_client_disconnected"
    elif isinstance(exc, ToolProtocolError):
        code = "invalid_aircraft_tool"
    else:
        code = "aircraft_tool_failed"
    return {
        "available": False,
        "error": {"code": code, "detail": str(exc)},
    }


AIRCRAFT_TOOL_NAMES = tuple(item.value for item in AircraftToolName)
