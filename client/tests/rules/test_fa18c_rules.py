from __future__ import annotations

from collections.abc import Iterable

from dcs_copilot.rules.base import Rule, RuleTransition, RuleTransitionType
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import (
    CanopyOpenWhileMovingRule,
    EjectionSeatNotArmedRule,
    GearOverspeedRule,
    MasterCautionRule,
    ParkingBrakeTaxiRule,
    RefuelingProbeLeftOutRule,
)
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import (
    AircraftState,
    CanopyState,
    FlightPhase,
    GearState,
    TelemetryValue,
)


def tv(value):
    return TelemetryValue(value=value, available=True, updated_at=0, source="test")


def state(**changes) -> AircraftState:
    result = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        flight_phase=FlightPhase.CRUISE,
        indicated_airspeed=tv(200.0),
        gear_position=tv(GearState.UP),
        canopy_state=tv(CanopyState.CLOSED),
        master_caution=tv(False),
        parking_brake=tv(False),
        refueling_probe=tv(False),
        ejection_seat_armed=tv(True),
        weight_on_wheels=tv(False),
    )
    for name, value in changes.items():
        setattr(result, name, tv(value) if name != "flight_phase" else value)
    return result


def evaluate(
    engine: RuleEngine,
    history: StateHistory,
    current: AircraftState,
    now: float,
) -> tuple[RuleTransition, ...]:
    history.record(current, timestamp=now)
    return engine.evaluate(current, history, now=now)


def engine_for(rules: Iterable[Rule]) -> tuple[RuleEngine, StateHistory]:
    return RuleEngine(rules), StateHistory()


def test_master_caution_debounces_and_resolves() -> None:
    engine, history = engine_for([MasterCautionRule()])
    caution = state(master_caution=True)
    assert evaluate(engine, history, caution, 1.0) == ()
    activated = evaluate(engine, history, caution, 1.25)
    assert activated[0].type is RuleTransitionType.ACTIVATED
    assert activated[0].issue.rule_id == "FA18_MASTER_CAUTION"
    assert len(engine.active_issues) == 1

    clear = state(master_caution=False)
    assert evaluate(engine, history, clear, 2.0) == ()
    resolved = evaluate(engine, history, clear, 2.5)
    assert resolved[0].type is RuleTransitionType.RESOLVED
    assert engine.active_issues == ()


def test_gear_overspeed_uses_airborne_check_and_clear_hysteresis() -> None:
    engine, history = engine_for([GearOverspeedRule()])
    safe = state(indicated_airspeed=249.0, gear_position=GearState.DOWN)
    assert evaluate(engine, history, safe, 0.0) == ()

    fast = state(indicated_airspeed=255.0, gear_position=GearState.DOWN)
    assert evaluate(engine, history, fast, 1.0) == ()
    activated = evaluate(engine, history, fast, 2.0)
    assert activated[0].issue.data["ias_knots"] == 255.0

    hysteresis = state(indicated_airspeed=245.0, gear_position=GearState.DOWN)
    assert evaluate(engine, history, hysteresis, 3.0) == ()
    assert len(engine.active_issues) == 1
    clear = state(indicated_airspeed=239.0, gear_position=GearState.DOWN)
    assert evaluate(engine, history, clear, 4.0) == ()
    assert evaluate(engine, history, clear, 5.0)[0].type is RuleTransitionType.RESOLVED

    on_ground = state(
        indicated_airspeed=270.0,
        gear_position=GearState.DOWN,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, on_ground, 6.0) == ()


def test_canopy_rule_warns_only_after_meaningful_movement() -> None:
    engine, history = engine_for([CanopyOpenWhileMovingRule()])
    slow = state(indicated_airspeed=19.0, canopy_state=CanopyState.OPEN)
    assert evaluate(engine, history, slow, 0.0) == ()
    moving = state(indicated_airspeed=25.0, canopy_state=CanopyState.MOVING)
    assert evaluate(engine, history, moving, 1.0) == ()
    assert (
        evaluate(engine, history, moving, 2.0)[0].type is RuleTransitionType.ACTIVATED
    )

    still_active = state(indicated_airspeed=15.0, canopy_state=CanopyState.OPEN)
    assert evaluate(engine, history, still_active, 3.0) == ()
    closed = state(indicated_airspeed=15.0, canopy_state=CanopyState.CLOSED)
    assert evaluate(engine, history, closed, 4.0) == ()
    assert evaluate(engine, history, closed, 4.5)[0].type is RuleTransitionType.RESOLVED


def test_parking_brake_requires_weight_on_wheels_and_taxi_motion() -> None:
    engine, history = engine_for([ParkingBrakeTaxiRule()])
    taxi = state(
        flight_phase=FlightPhase.TAXI,
        indicated_airspeed=7.0,
        parking_brake=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, taxi, 0.0) == ()
    assert evaluate(engine, history, taxi, 2.0)[0].type is RuleTransitionType.ACTIVATED

    rolling_slowly = state(
        flight_phase=FlightPhase.TAXI,
        indicated_airspeed=3.0,
        parking_brake=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, rolling_slowly, 3.0) == ()
    released = state(
        flight_phase=FlightPhase.TAXI,
        indicated_airspeed=3.0,
        parking_brake=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, released, 4.0) == ()
    assert (
        evaluate(engine, history, released, 4.5)[0].type is RuleTransitionType.RESOLVED
    )


def test_ejection_seat_rule_is_phase_restricted() -> None:
    engine, history = engine_for([EjectionSeatNotArmedRule()])
    startup = state(
        flight_phase=FlightPhase.STARTUP,
        ejection_seat_armed=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, startup, 0.0) == ()

    taxi = state(
        flight_phase=FlightPhase.TAXI,
        ejection_seat_armed=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, taxi, 1.0) == ()
    assert evaluate(engine, history, taxi, 3.0)[0].type is RuleTransitionType.ACTIVATED

    armed = state(
        flight_phase=FlightPhase.TAXI,
        ejection_seat_armed=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, armed, 4.0) == ()
    assert evaluate(engine, history, armed, 4.25)[0].type is RuleTransitionType.RESOLVED


def test_refueling_probe_issue_excludes_refueling_and_preserves_unknown() -> None:
    engine, history = engine_for([RefuelingProbeLeftOutRule()])
    probe_out = state(refueling_probe=True)
    assert evaluate(engine, history, probe_out, 0.0) == ()
    activated = evaluate(engine, history, probe_out, 2.0)
    assert activated[0].issue.message == "Refueling probe is still out."

    refueling = state(
        flight_phase=FlightPhase.REFUELING,
        refueling_probe=True,
    )
    assert evaluate(engine, history, refueling, 3.0)[0].type is (
        RuleTransitionType.DISABLED
    )

    unavailable = state(refueling_probe=True)
    unavailable.refueling_probe = TelemetryValue.unavailable("test")
    assert evaluate(engine, history, unavailable, 4.0) == ()


def test_unavailable_required_field_immediately_disables_active_rule() -> None:
    engine, history = engine_for([MasterCautionRule()])
    caution = state(master_caution=True)
    evaluate(engine, history, caution, 0.0)
    evaluate(engine, history, caution, 0.25)
    unavailable = state(master_caution=True)
    unavailable.master_caution = TelemetryValue.unavailable("test")
    transition = evaluate(engine, history, unavailable, 0.3)
    assert transition[0].type is RuleTransitionType.DISABLED
    assert engine.active_issues == ()


def test_cooldown_suppresses_notification_not_active_issue() -> None:
    engine, history = engine_for([MasterCautionRule()])
    caution = state(master_caution=True)
    evaluate(engine, history, caution, 0.0)
    first = evaluate(engine, history, caution, 0.25)[0]
    assert first.notification_eligible
    clear = state(master_caution=False)
    evaluate(engine, history, clear, 1.0)
    evaluate(engine, history, clear, 1.5)
    evaluate(engine, history, caution, 2.0)
    second = evaluate(engine, history, caution, 2.25)[0]
    assert not second.notification_eligible
    assert len(engine.active_issues) == 1
