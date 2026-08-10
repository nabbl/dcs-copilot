from __future__ import annotations

from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import (
    AircraftState,
    FlightPhase,
    TelemetryValue,
)
from dcs_copilot.state.store import AircraftStateStore
from dcs_copilot.tools import AircraftToolExecutor
from dcs_copilot_protocol import (
    AIRCRAFT_TOOL_VERSION,
    AircraftToolRequest,
    AircraftToolResult,
    ControlMessage,
)


def test_executor_returns_requested_fields_only_and_preserves_unavailable(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    store.current = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        refueling_probe=TelemetryValue(
            True,
            available=True,
            updated_at=10.0,
            source="DCS-BIOS:EXT_REFUEL_PROBE",
        ),
    )
    executor = AircraftToolExecutor(store)
    request = AircraftToolRequest.create(
        "get_aircraft_state",
        {"fields": ["refueling_probe", "fuel_quantity"]},
        request_id="state-request",
    )

    result = executor.execute(request)

    assert set(result["fields"]) == {"refueling_probe", "fuel_quantity"}
    assert result["fields"]["refueling_probe"] == {
        "status": "AVAILABLE",
        "value": True,
        "updated_at": 10.0,
        "source": "DCS-BIOS:EXT_REFUEL_PROBE",
    }
    assert result["fields"]["fuel_quantity"]["status"] == "UNAVAILABLE"
    assert result["fields"]["fuel_quantity"]["value"] is None


def test_executor_exposes_deterministic_issues_phase_and_recent_events(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    state = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        flight_phase=FlightPhase.CRUISE,
        master_caution=TelemetryValue(True, available=True, updated_at=20.0),
        refueling_probe=TelemetryValue(False, available=True, updated_at=20.0),
    )
    store.current = state
    store.history.record(state, timestamp=20.0)
    store.rule_engine.evaluate(state, store.history, now=20.0)
    store.rule_engine.evaluate(state, store.history, now=20.25)
    executor = AircraftToolExecutor(store, clock=lambda: 21.0)

    issues = executor.execute(AircraftToolRequest.create("get_active_issues", {}))
    phase = executor.execute(AircraftToolRequest.create("get_flight_phase", {}))
    events = executor.execute(
        AircraftToolRequest.create(
            "get_recent_events",
            {"seconds": 10, "limit": 5},
        )
    )

    assert issues["available"] is True
    assert issues["issues"][0]["rule_id"] == "FA18_MASTER_CAUTION"
    assert phase == {"available": True, "flight_phase": "CRUISE"}
    assert events["available"] is True
    assert len(events["events"]) == 1
    assert events["events"][0]["rule_id"] == "FA18_MASTER_CAUTION"
    assert events["events"][0]["status"] == "RAISED"


def test_executor_rejects_non_allowlisted_tool_without_executing_it() -> None:
    executor = AircraftToolExecutor(None)
    malicious = ControlMessage(
        "tool.request",
        {
            "tool_version": AIRCRAFT_TOOL_VERSION,
            "tool": "run_shell",
            "arguments": {"command": "whoami"},
        },
        message_id="malicious-request",
    )

    result = AircraftToolResult.from_control(executor.handle_control(malicious))

    assert result.request_id == "malicious-request"
    assert result.ok is False
    assert result.error is not None
    assert result.error["code"] == "tool_not_allowed"


def test_executor_reports_disconnected_state_as_unavailable() -> None:
    executor = AircraftToolExecutor(None)
    phase = executor.execute(AircraftToolRequest.create("get_flight_phase", {}))
    issues = executor.execute(AircraftToolRequest.create("get_active_issues", {}))

    assert phase == {"available": False, "flight_phase": None}
    assert issues == {
        "available": False,
        "coverage": "UNAVAILABLE",
        "unavailable_rule_ids": [],
        "issues": [],
    }
