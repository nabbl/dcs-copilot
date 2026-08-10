from __future__ import annotations

import asyncio

import pytest
from dcs_copilot_cloud.tools import (
    LocalAircraftToolBroker,
    LocalAircraftToolDisconnected,
    LocalAircraftToolTimeout,
)
from dcs_copilot_protocol import (
    AircraftToolRequest,
    AircraftToolResult,
    ControlMessage,
    ToolProtocolError,
)


def test_broker_correlates_tool_result_to_request() -> None:
    async def scenario() -> tuple[ControlMessage, dict[str, object]]:
        sent: asyncio.Queue[ControlMessage] = asyncio.Queue()

        async def send(message: ControlMessage) -> None:
            await sent.put(message)

        broker = LocalAircraftToolBroker(send, timeout_seconds=1)
        task = asyncio.create_task(broker.request("get_active_issues", {}))
        control = await sent.get()
        request = AircraftToolRequest.from_control(control)
        broker.resolve(
            AircraftToolResult.success(
                request,
                {
                    "available": True,
                    "coverage": "AVAILABLE",
                    "unavailable_rule_ids": [],
                    "issues": [],
                },
            ).to_control()
        )
        return control, await task

    control, result = asyncio.run(scenario())
    assert control.type == "tool.request"
    assert result == {
        "available": True,
        "coverage": "AVAILABLE",
        "unavailable_rule_ids": [],
        "issues": [],
    }


def test_broker_rejects_mismatched_and_unsolicited_correlation() -> None:
    async def scenario() -> None:
        async def send(_message: ControlMessage) -> None:
            return None

        broker = LocalAircraftToolBroker(send, timeout_seconds=1)
        unsolicited = ControlMessage(
            "tool.result",
            {
                "tool_version": 1,
                "tool": "get_flight_phase",
                "ok": True,
                "result": {"available": False, "flight_phase": None},
            },
            correlation_id="not-pending",
        )
        with pytest.raises(ToolProtocolError, match="no matching"):
            broker.resolve(unsolicited)

    asyncio.run(scenario())


def test_broker_times_out_when_client_does_not_return_result() -> None:
    async def scenario() -> None:
        async def send(_message: ControlMessage) -> None:
            return None

        broker = LocalAircraftToolBroker(send, timeout_seconds=0.01)
        with pytest.raises(LocalAircraftToolTimeout, match="timed out"):
            await broker.request("get_flight_phase", {})

    asyncio.run(scenario())


def test_broker_fails_pending_request_on_disconnect() -> None:
    async def scenario() -> None:
        sent = asyncio.Event()

        async def send(_message: ControlMessage) -> None:
            sent.set()

        broker = LocalAircraftToolBroker(send, timeout_seconds=1)
        task = asyncio.create_task(broker.request("get_flight_phase", {}))
        await sent.wait()
        broker.disconnect()
        with pytest.raises(LocalAircraftToolDisconnected, match="disconnected"):
            await task

    asyncio.run(scenario())
