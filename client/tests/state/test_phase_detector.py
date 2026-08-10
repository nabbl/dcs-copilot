from __future__ import annotations

from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import (
    AircraftState,
    FlightPhase,
    GearState,
    TelemetryValue,
)
from dcs_copilot.state.phase_detector import FlightPhaseDetector, PhaseDetectorConfig


def tv(value):
    return TelemetryValue(value=value, available=True, updated_at=0, source="test")


def aircraft_state(
    *,
    wow: bool,
    speed: float,
    rpm: float = 70,
    gear: GearState = GearState.UP,
    probe: bool = False,
    altitude: float = 1000,
    fuel: float = 10000,
) -> AircraftState:
    return AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        indicated_airspeed=tv(speed),
        altitude_msl=tv(altitude),
        gear_position=tv(gear),
        weight_on_wheels=tv(wow),
        engine_rpm_left=tv(rpm),
        engine_rpm_right=tv(rpm),
        refueling_probe=tv(probe),
        fuel_quantity=tv(fuel),
    )


def detect(
    detector: FlightPhaseDetector,
    history: StateHistory,
    state: AircraftState,
    now: float,
) -> FlightPhase:
    history.record(state, timestamp=now)
    return detector.update(state, history, now=now)


def immediate_detector() -> FlightPhaseDetector:
    return FlightPhaseDetector(
        PhaseDetectorConfig(default_dwell_seconds=0, phase_dwell_seconds={})
    )


def test_ground_and_takeoff_phases() -> None:
    detector = immediate_detector()
    history = StateHistory()
    assert (
        detect(detector, history, aircraft_state(wow=True, speed=0, rpm=0), 0)
        is FlightPhase.COLD_DARK
    )
    assert (
        detect(detector, history, aircraft_state(wow=True, speed=0, rpm=30), 1)
        is FlightPhase.STARTUP
    )
    assert (
        detect(detector, history, aircraft_state(wow=True, speed=10), 2)
        is FlightPhase.TAXI
    )
    assert (
        detect(detector, history, aircraft_state(wow=True, speed=100), 3)
        is FlightPhase.TAKEOFF
    )
    assert (
        detect(
            detector,
            history,
            aircraft_state(wow=False, speed=150, gear=GearState.DOWN),
            4,
        )
        is FlightPhase.TAKEOFF
    )


def test_airborne_special_phases_and_conservative_unknown() -> None:
    detector = immediate_detector()
    history = StateHistory()
    assert (
        detect(
            detector,
            history,
            aircraft_state(wow=False, speed=220, gear=GearState.DOWN),
            0,
        )
        is FlightPhase.APPROACH
    )
    assert (
        detect(
            detector,
            history,
            aircraft_state(wow=False, speed=140, gear=GearState.DOWN, altitude=980),
            1,
        )
        is FlightPhase.LANDING
    )
    assert (
        detect(
            detector,
            history,
            aircraft_state(wow=False, speed=250, probe=True, altitude=980),
            1.5,
        )
        is FlightPhase.CRUISE
    )
    assert (
        detect(
            detector,
            history,
            aircraft_state(wow=False, speed=250, probe=True, altitude=980, fuel=10100),
            2,
        )
        is FlightPhase.REFUELING
    )
    unavailable = aircraft_state(wow=False, speed=250)
    unavailable.weight_on_wheels = TelemetryValue.unavailable("test")
    assert detect(detector, history, unavailable, 3) is FlightPhase.UNKNOWN


def test_climb_and_cruise_use_altitude_history() -> None:
    detector = immediate_detector()
    history = StateHistory()
    assert (
        detect(
            detector, history, aircraft_state(wow=False, speed=250, altitude=1000), 0
        )
        is FlightPhase.CRUISE
    )
    assert (
        detect(
            detector, history, aircraft_state(wow=False, speed=250, altitude=1200), 10
        )
        is FlightPhase.CLIMB
    )


def test_hysteresis_requires_stable_candidate() -> None:
    detector = FlightPhaseDetector(PhaseDetectorConfig(default_dwell_seconds=2))
    history = StateHistory()
    taxi = aircraft_state(wow=True, speed=10)
    assert detect(detector, history, taxi, 0) is FlightPhase.UNKNOWN
    assert detect(detector, history, taxi, 1) is FlightPhase.UNKNOWN
    assert detect(detector, history, taxi, 2.1) is FlightPhase.TAXI
