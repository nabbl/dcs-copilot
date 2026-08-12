"""Tests for BackendAircraftToolExecutor: synchronous, in-process tool execution."""

from __future__ import annotations

import pytest

from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey
from dcs_copilot_cloud.state.store import AircraftStateStore
from dcs_copilot_cloud.tools import (
    AircraftToolName,
    AircraftToolRequest,
    BackendAircraftToolExecutor,
    ToolProtocolError,
)

from .helpers import minimal_gear_down, minimal_wow_grounded, set_int


def _connected_store(now: float) -> AircraftStateStore:
    store = AircraftStateStore()
    minimal_wow_grounded(store.raw, now=now)
    set_int(store.raw, "BATTERY_SW", 0, now=now)
    store.update(aircraft="FA-18C_hornet", connected=True, now=now)
    return store


def test_execute_get_flight_phase_without_broker() -> None:
    store = _connected_store(100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 100.0)
    request = AircraftToolRequest.create(AircraftToolName.GET_FLIGHT_PHASE, {})
    result = executor.execute(request)
    assert "flight_phase" in result


def test_execute_works_with_no_store() -> None:
    executor = BackendAircraftToolExecutor(None, clock=lambda: 0.0)
    request = AircraftToolRequest.create(AircraftToolName.GET_ACTIVE_ISSUES, {})
    result = executor.execute(request)
    assert result["available"] is False


def test_get_active_issues_empty_has_readiness_false() -> None:
    store = _connected_store(100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 100.0)
    request = AircraftToolRequest.create(AircraftToolName.GET_ACTIVE_ISSUES, {})
    result = executor.execute(request)
    assert result["issues"] == []
    assert result["readiness"] is False
    assert result["ready_confirmed"] is False


def test_checklist_start_advance_confirm_stop_locally() -> None:
    store = _connected_store(100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 100.0)

    start_request = AircraftToolRequest.create(
        AircraftToolName.START_GUIDED_CHECKLIST,
        {"checklist_id": "fa18c_startup", "stage": "pre-start"},
    )
    start_result = executor.execute(start_request)
    assert start_result["started"] is True
    assert start_result["stage"] == "pre-start"

    next_request = AircraftToolRequest.create(AircraftToolName.GET_NEXT_CHECKLIST_ITEM, {})
    next_result = executor.execute(next_request)
    assert next_result["item"] is not None
    item_id = next_result["item"]["id"]

    confirm_request = AircraftToolRequest.create(
        AircraftToolName.CONFIRM_MANUAL_CHECKLIST_ITEM, {"item_id": item_id}
    )
    # This item is a STATE item (not manual), confirming has no effect on its
    # own evaluated status, but the call itself must succeed synchronously.
    confirm_result = executor.execute(confirm_request)
    assert confirm_result["confirmed"] is True
    assert confirm_result["item_id"] == item_id

    stop_request = AircraftToolRequest.create(AircraftToolName.STOP_GUIDED_CHECKLIST, {})
    stop_result = executor.execute(stop_request)
    assert stop_result["stopped"] is True


def test_unknown_tool_name_raises_tool_protocol_error() -> None:
    with pytest.raises(ToolProtocolError, match="not allowed"):
        AircraftToolRequest.create("delete_everything", {})


def test_disallowed_aircraft_state_field_raises_tool_protocol_error() -> None:
    with pytest.raises(ToolProtocolError, match="not allowed"):
        AircraftToolRequest.create(
            AircraftToolName.GET_AIRCRAFT_STATE,
            {"fields": ["not_an_allowed_field"]},
        )


def test_execute_get_flight_phase_returns_result_synchronously() -> None:
    store = _connected_store(100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 100.0)
    request = AircraftToolRequest.create(AircraftToolName.GET_FLIGHT_PHASE, {})
    result = executor.execute(request)
    assert "flight_phase" in result
