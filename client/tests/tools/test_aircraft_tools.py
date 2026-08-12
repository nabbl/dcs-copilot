from __future__ import annotations

from dcs_copilot.checklists import (
    ChecklistDefinition,
    ChecklistItem,
    ChecklistStage,
    VerificationType,
)
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import (
    AircraftState,
    CanopyState,
    FlightPhase,
    MasterArmState,
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


def test_executor_exposes_checklist_status_and_missing_items(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    current = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        parking_brake=TelemetryValue(True, available=True, updated_at=1.0),
        master_arm=TelemetryValue(
            MasterArmState.SAFE, available=True, updated_at=1.0
        ),
        battery_on=TelemetryValue(True, available=True, updated_at=1.0),
        apu_ready=TelemetryValue(True, available=True, updated_at=1.0),
        engine_rpm_left=TelemetryValue(70, available=True, updated_at=1.0),
        engine_rpm_right=TelemetryValue(70, available=True, updated_at=1.0),
        left_generator_normal=TelemetryValue(True, available=True, updated_at=1.0),
        right_generator_normal=TelemetryValue(True, available=True, updated_at=1.0),
        bleed_air_normal=TelemetryValue(True, available=True, updated_at=1.0),
        ins_mode=TelemetryValue("NAV", available=True, updated_at=1.0),
        obogs_on=TelemetryValue(False, available=True, updated_at=1.0),
        ejection_seat_armed=TelemetryValue(False, available=True, updated_at=1.0),
        canopy_state=TelemetryValue(CanopyState.CLOSED, available=True, updated_at=1.0),
        takeoff_trim_confirmed=TelemetryValue(False, available=True, updated_at=1.0),
        master_caution=TelemetryValue(False, available=True, updated_at=1.0),
    )
    store.current = current
    store.history.record(current, timestamp=1.0)
    executor = AircraftToolExecutor(store, clock=lambda: 2.0)

    status = executor.execute(
        AircraftToolRequest.create(
            "get_checklist_status",
            {
                "checklist_id": "fa18c_startup",
                "stage": "before-taxi",
                "include_complete": False,
            },
        )
    )
    missing = executor.execute(
        AircraftToolRequest.create(
            "get_missing_checklist_items",
            {"checklist_id": "fa18c_startup", "stage": "before-taxi"},
        )
    )

    assert status["complete"] is False
    assert {item["id"] for item in status["items"]} == {
        "obogs_on",
        "ejection_seat_armed",
        "takeoff_trim",
    }
    assert [item["status"] for item in missing["items"]] == [
        "incomplete",
        "incomplete",
        "incomplete",
    ]


def test_default_startup_gaps_include_cold_and_dark_dependencies(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    store.current = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        parking_brake=TelemetryValue(True, available=True, updated_at=1.0),
        master_arm=TelemetryValue(
            MasterArmState.SAFE, available=True, updated_at=1.0
        ),
        battery_on=TelemetryValue(False, available=True, updated_at=1.0),
        apu_ready=TelemetryValue(False, available=True, updated_at=1.0),
        engine_rpm_left=TelemetryValue(0, available=True, updated_at=1.0),
        engine_rpm_right=TelemetryValue(0, available=True, updated_at=1.0),
    )
    executor = AircraftToolExecutor(store, clock=lambda: 2.0)

    missing = executor.execute(
        AircraftToolRequest.create(
            "get_missing_checklist_items",
            {"checklist_id": "fa18c_startup"},
        )
    )

    assert missing["stage"] == "before-taxi"
    assert missing["complete"] is False
    assert {item["id"] for item in missing["items"]} >= {
        "battery_on",
        "apu_ready",
        "left_engine_running",
        "right_engine_running",
    }


def test_executor_missing_checklist_items_excludes_not_applicable(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    store.current = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        obogs_on=TelemetryValue(False, available=True, updated_at=1.0),
        airborne=TelemetryValue(False, available=True, updated_at=1.0),
    )
    store.checklist_engine.definitions["test"] = ChecklistDefinition(
        id="test",
        aircraft="FA-18C_hornet",
        label="Test",
        stages=(
            ChecklistStage(
                id="stage",
                label="Stage",
                items=(
                    ChecklistItem(
                        "obogs_on",
                        "OBOGS",
                        VerificationType.STATE,
                        expected={"field": "obogs_on", "equals": True},
                    ),
                    ChecklistItem(
                        "probe_stowed",
                        "Probe",
                        VerificationType.STATE,
                        expected={"field": "refueling_probe", "equals": False},
                        applicable_if={"airborne": True},
                    ),
                ),
            ),
        ),
    )
    executor = AircraftToolExecutor(store)

    status = executor.execute(
        AircraftToolRequest.create(
            "get_checklist_status",
            {"checklist_id": "test", "stage": "stage"},
        )
    )
    missing = executor.execute(
        AircraftToolRequest.create(
            "get_missing_checklist_items",
            {"checklist_id": "test", "stage": "stage"},
        )
    )

    assert [item["status"] for item in status["items"]] == [
        "incomplete",
        "not_applicable",
    ]
    assert [item["id"] for item in missing["items"]] == ["obogs_on"]


def test_executor_supports_guided_manual_checklist_items(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    store.current = AircraftState(aircraft="FA-18C_hornet", connected=True)
    executor = AircraftToolExecutor(store)

    started = executor.execute(
        AircraftToolRequest.create(
            "start_guided_checklist",
            {"checklist_id": "fa18c_startup", "stage": "before-taxi"},
        )
    )
    confirmed = executor.execute(
        AircraftToolRequest.create(
            "confirm_manual_checklist_item",
            {"item_id": "helmet"},
        )
    )
    stopped = executor.execute(AircraftToolRequest.create("stop_guided_checklist", {}))

    assert started == {
        "started": True,
        "checklist_id": "fa18c_startup",
        "stage": "before-taxi",
    }
    assert confirmed == {"confirmed": True, "item_id": "helmet"}
    assert stopped == {"stopped": True}
