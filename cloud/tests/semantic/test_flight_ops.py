from __future__ import annotations

import pytest
from dcs_copilot_cloud.flight_ops import FlightOpsCoordinator, FlightOpsStage
from dcs_copilot_cloud.ground_ops import ReadinessStatus
from dcs_copilot_cloud.state.models import (
    AircraftState,
    FlapState,
    FlightPhase,
    GearState,
    TelemetryValue,
)


def _value(value, *, stale: bool = False) -> TelemetryValue:
    return TelemetryValue(value, True, 100.0, "test", stale)


def _climbing_state() -> AircraftState:
    return AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        flight_phase=FlightPhase.CLIMB,
        airborne=_value(True),
        gear_position=_value(GearState.UP),
        flap_position=_value(FlapState.AUTO),
        launch_bar_deployed=_value(False),
    )


def test_departure_cleanup_requires_positive_observation_of_every_item() -> None:
    snapshot = FlightOpsCoordinator().evaluate(_climbing_state())

    assert snapshot.available is True
    assert snapshot.stage is FlightOpsStage.DEPARTURE
    assert snapshot.departure_cleanup.status is ReadinessStatus.READY


def test_departure_cleanup_reports_known_failure_before_unknown_telemetry() -> None:
    state = _climbing_state()
    state.gear_position = _value(GearState.DOWN)
    state.flap_position = TelemetryValue.unavailable()

    report = FlightOpsCoordinator().departure_cleanup(state)

    assert report.status is ReadinessStatus.BLOCKED
    assert [item.id for item in report.blocking_items] == ["gear_up"]
    assert [item.id for item in report.unknown_items] == ["flaps_auto"]


def test_departure_cleanup_is_not_applicable_outside_departure() -> None:
    state = _climbing_state()
    state.flight_phase = FlightPhase.CRUISE

    snapshot = FlightOpsCoordinator().evaluate(state)

    assert snapshot.stage is FlightOpsStage.EN_ROUTE
    assert snapshot.departure_cleanup.status is ReadinessStatus.NOT_APPLICABLE


def test_departure_cleanup_does_not_prompt_gear_retraction_on_takeoff_roll() -> None:
    state = _climbing_state()
    state.flight_phase = FlightPhase.TAKEOFF
    state.airborne = _value(False)
    state.gear_position = _value(GearState.DOWN)

    report = FlightOpsCoordinator().departure_cleanup(state)

    assert report.status is ReadinessStatus.NOT_APPLICABLE
    assert report.items == ()


@pytest.mark.parametrize(
    ("phase", "stage"),
    [
        (FlightPhase.COMBAT, FlightOpsStage.COMBAT),
        (FlightPhase.REFUELING, FlightOpsStage.REFUELING),
        (FlightPhase.APPROACH, FlightOpsStage.ARRIVAL),
        (FlightPhase.LANDING, FlightOpsStage.ARRIVAL),
    ],
)
def test_flight_stage_mapping(phase: FlightPhase, stage: FlightOpsStage) -> None:
    state = _climbing_state()
    state.flight_phase = phase
    assert FlightOpsCoordinator().evaluate(state).stage is stage


def test_disconnected_flight_ops_fail_closed() -> None:
    snapshot = FlightOpsCoordinator().evaluate(AircraftState())
    assert snapshot.available is False
    assert snapshot.stage is FlightOpsStage.UNKNOWN
    assert snapshot.departure_cleanup.status is ReadinessStatus.UNKNOWN
