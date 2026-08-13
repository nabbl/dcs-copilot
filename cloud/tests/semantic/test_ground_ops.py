"""Journey-level tests for deterministic ground operations and takeoff gates."""

from __future__ import annotations

from dcs_copilot_cloud.checklists.engine import ChecklistEngine
from dcs_copilot_cloud.checklists.fa18c import fa18c_checklists
from dcs_copilot_cloud.ground_ops import (
    GroundOpsCoordinator,
    GroundOpsPhase,
    LineupState,
    ReadinessStatus,
    TakeoffOperation,
)
from dcs_copilot_cloud.state.history import StateHistory
from dcs_copilot_cloud.state.models import (
    AircraftState,
    CanopyState,
    FlapState,
    FlightPhase,
    GearState,
    MasterArmState,
    TelemetryValue,
)


def tv(value):
    return TelemetryValue(value, available=True, updated_at=100.0)


def ready_hornet() -> tuple[AircraftState, ChecklistEngine]:
    state = AircraftState(aircraft="FA-18C_hornet", connected=True)
    state.flight_phase = FlightPhase.STARTUP
    state.weight_on_wheels = tv(True)
    state.ground_speed = tv(0.0)
    state.indicated_airspeed = tv(0.0)
    state.engine_rpm_left = tv(70.0)
    state.engine_rpm_right = tv(70.0)
    state.flap_position = tv(FlapState.HALF)
    state.gear_position = tv(GearState.DOWN)
    state.hook_position = tv(False)
    state.speed_brake = tv(0.0)
    state.master_arm = tv(MasterArmState.SAFE)
    state.ejection_seat_armed = tv(True)
    state.obogs_on = tv(True)
    state.canopy_state = tv(CanopyState.CLOSED)
    state.takeoff_trim_confirmed = tv(True)
    state.wing_fold_spread = tv(True)
    state.master_caution = tv(False)
    state.launch_bar_deployed = tv(False)
    state.takeoff_sequence = tv(False)
    state.carrier_launch_sequence = tv(False)
    checklist = ChecklistEngine(fa18c_checklists())
    checklist.start("fa18c_startup")
    checklist.confirm_manual_item("flight_controls_check")
    return state, checklist


def test_land_takeoff_gate_reports_ready_only_after_positive_verification() -> None:
    state, checklist = ready_hornet()
    report = GroundOpsCoordinator().takeoff_readiness(
        state, checklist, operation=TakeoffOperation.LAND
    )
    assert report.status is ReadinessStatus.READY
    assert report.blocking_items == ()
    assert report.unknown_items == ()


def test_takeoff_gate_separates_blocking_and_unknown_items() -> None:
    state, checklist = ready_hornet()
    state.flap_position = tv(FlapState.AUTO)
    state.takeoff_trim_confirmed = TelemetryValue.unavailable()
    report = GroundOpsCoordinator().takeoff_readiness(
        state, checklist, operation=TakeoffOperation.LAND
    )
    assert report.status is ReadinessStatus.BLOCKED
    assert {item.id for item in report.blocking_items} == {"flaps_half"}
    assert {item.id for item in report.unknown_items} == {"takeoff_trim"}


def test_unconfirmed_flight_controls_explains_the_required_manual_check() -> None:
    state, checklist = ready_hornet()
    checklist.reset()
    report = GroundOpsCoordinator().takeoff_readiness(
        state, checklist, operation=TakeoffOperation.LAND
    )
    flight_controls = next(
        item for item in report.unknown_items if item.id == "flight_controls_check"
    )

    assert "full-and-free stick and rudder" in flight_controls.label
    assert "FCS indications" in flight_controls.reason


def test_auto_operation_refuses_to_guess_land_runway_context() -> None:
    state, checklist = ready_hornet()
    report = GroundOpsCoordinator().takeoff_readiness(
        state, checklist, operation=TakeoffOperation.AUTO
    )
    assert report.status is ReadinessStatus.UNKNOWN
    assert {item.id for item in report.unknown_items} == {"takeoff_operation"}


def test_carrier_launch_signal_is_the_only_confirmed_lineup_state() -> None:
    state, checklist = ready_hornet()
    state.launch_bar_deployed = tv(True)
    state.carrier_launch_sequence = tv(True)
    snapshot = GroundOpsCoordinator().evaluate(
        state,
        StateHistory(),
        checklist,
        now=100.0,
        operation=TakeoffOperation.CARRIER,
    )
    assert snapshot.phase is GroundOpsPhase.CARRIER_LAUNCH
    assert snapshot.lineup_state is LineupState.CARRIER_CONFIRMED
    assert snapshot.takeoff.status is ReadinessStatus.READY


def test_land_ground_state_never_claims_runway_alignment() -> None:
    state, checklist = ready_hornet()
    state.flight_phase = FlightPhase.TAXI
    state.ground_speed = tv(10.0)
    snapshot = GroundOpsCoordinator().evaluate(
        state,
        StateHistory(),
        checklist,
        now=100.0,
        operation=TakeoffOperation.LAND,
    )
    assert snapshot.phase is GroundOpsPhase.TAXI
    assert snapshot.lineup_state is LineupState.UNCONFIRMED
