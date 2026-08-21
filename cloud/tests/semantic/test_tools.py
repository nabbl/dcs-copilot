"""Tests for BackendAircraftToolExecutor: synchronous, in-process tool execution."""

from __future__ import annotations

import pytest
from dcs_copilot_cloud.state.models import FlightPhase
from dcs_copilot_cloud.state.store import AircraftStateStore
from dcs_copilot_cloud.tools import (
    AircraftToolName,
    AircraftToolRequest,
    BackendAircraftToolExecutor,
    ToolProtocolError,
    validate_tool_result,
)

from .helpers import minimal_wow_grounded, set_int


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

    next_request = AircraftToolRequest.create(
        AircraftToolName.GET_NEXT_CHECKLIST_ITEM, {}
    )
    next_result = executor.execute(next_request)
    assert next_result["item"] is not None
    current_id = next_result["item"]["id"]
    confirm_request = AircraftToolRequest.create(
        AircraftToolName.CONFIRM_CHECKLIST_ITEM,
        {"item_id": current_id},
    )
    confirm_result = executor.execute(confirm_request)
    validate_tool_result(confirm_request.tool, confirm_result)
    assert confirm_result["confirmed"] is True
    assert confirm_result["item_id"] == current_id
    assert confirm_result["confirmation_source"] == "pilot_override"
    assert confirm_result["next_item"] is not None
    assert confirm_result["next_item"]["id"] != current_id

    stop_request = AircraftToolRequest.create(
        AircraftToolName.STOP_GUIDED_CHECKLIST, {}
    )
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


def test_ground_ops_and_takeoff_readiness_tools_are_bounded_and_validated() -> None:
    store = _connected_store(100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 100.0)

    ground_request = AircraftToolRequest.create(
        AircraftToolName.GET_GROUND_OPS_STATUS, {}
    )
    ground = executor.execute(ground_request)
    validate_tool_result(ground_request.tool, ground)
    assert ground["available"] is True
    assert ground["lineup_state"] == "UNCONFIRMED"

    takeoff_request = AircraftToolRequest.create(
        AircraftToolName.GET_TAKEOFF_READINESS,
        {"operation": "LAND"},
    )
    takeoff = executor.execute(takeoff_request)
    validate_tool_result(takeoff_request.tool, takeoff)
    assert takeoff["status"] in {"BLOCKED", "UNKNOWN"}
    assert takeoff["operation"] == "LAND"


def test_takeoff_readiness_rejects_unknown_operation() -> None:
    with pytest.raises(ToolProtocolError, match="AUTO, LAND, or CARRIER"):
        AircraftToolRequest.create(
            AircraftToolName.GET_TAKEOFF_READINESS,
            {"operation": "SPACE"},
        )


def test_flight_status_consolidates_departure_cleanup_and_issue_coverage() -> None:
    now = 100.0
    store = AircraftStateStore()
    for identifier, value in (
        ("EXT_WOW_NOSE", 0),
        ("EXT_WOW_LEFT", 0),
        ("EXT_WOW_RIGHT", 0),
        ("GEAR_LEVER", 1),
        ("FLP_LG_NOSE_GEAR_LT", 0),
        ("FLP_LG_LEFT_GEAR_LT", 0),
        ("FLP_LG_RIGHT_GEAR_LT", 0),
        ("FLAP_SW", 0),
        ("LAUNCH_BAR_SW", 0),
    ):
        set_int(store.raw, identifier, value, now=now)
    store.update(aircraft="FA-18C_hornet", connected=True, now=now)
    store.current.flight_phase = FlightPhase.CLIMB
    executor = BackendAircraftToolExecutor(store, clock=lambda: now + 4.0)
    request = AircraftToolRequest.create(AircraftToolName.GET_FLIGHT_STATUS, {})

    result = executor.execute(request)

    validate_tool_result(request.tool, result)
    assert result["flight_stage"] == "DEPARTURE"
    assert result["departure_cleanup"]["status"] == "READY"
    assert result["issues_coverage"] in {"AVAILABLE", "PARTIAL"}


def test_hornet_knowledge_tool_returns_pinned_source_metadata() -> None:
    executor = BackendAircraftToolExecutor(None)
    request = AircraftToolRequest.create(
        AircraftToolName.GET_HORNET_KNOWLEDGE,
        {"topic": "tacan_navigation"},
    )

    result = executor.execute(request)

    validate_tool_result(request.tool, result)
    assert result["corpus_version"] == "fa18c-ed-2026.08.2"
    assert result["card"]["source"]["publisher"] == "Eagle Dynamics"
    assert result["card"]["source"]["pages"] == "136-138"


def test_case_i_knowledge_tool_returns_guidable_steps() -> None:
    executor = BackendAircraftToolExecutor(None)
    request = AircraftToolRequest.create(
        AircraftToolName.GET_HORNET_KNOWLEDGE,
        {"topic": "case_i_recovery"},
    )

    result = executor.execute(request)

    validate_tool_result(request.tool, result)
    assert result["card"]["title"] == "CASE I carrier recovery overview"
    assert len(result["card"]["steps"]) == 7
    assert result["card"]["source"]["pages"] == "108-113"


def test_hornet_knowledge_rejects_unsupported_topics() -> None:
    with pytest.raises(ToolProtocolError, match="must be one of"):
        AircraftToolRequest.create(
            AircraftToolName.GET_HORNET_KNOWLEDGE,
            {"topic": "weapon_employment"},
        )
