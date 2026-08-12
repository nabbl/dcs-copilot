from __future__ import annotations

from collections.abc import Iterable

import pytest

from dcs_copilot.rules.base import Rule, RuleTransition, RuleTransitionType
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import (
    FA18CRuleThresholds,
    CanopyOpenWhileMovingRule,
    EjectionSeatNotArmedRule,
    GearOverspeedRule,
    MasterCautionRule,
    ParkingBrakeTaxiRule,
    RefuelingProbeLeftOutRule,
    TaxiLightOffRule,
    declarative_fa18c_rules,
    fa18c_rules,
)
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import (
    AircraftState,
    CanopyState,
    FlapState,
    FlightPhase,
    GearState,
    MasterArmState,
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
        ground_speed=tv(200.0),
        gear_position=tv(GearState.UP),
        canopy_state=tv(CanopyState.CLOSED),
        master_caution=tv(False),
        parking_brake=tv(False),
        taxi_light_on=tv(True),
        refueling_probe=tv(False),
        ejection_seat_armed=tv(True),
        weight_on_wheels=tv(False),
    )
    for name, value in changes.items():
        setattr(result, name, tv(value) if name != "flight_phase" else value)
    return result


def rich_state(**changes) -> AircraftState:
    result = state(
        flight_phase=FlightPhase.TAKEOFF,
        indicated_airspeed=100.0,
        gear_position=GearState.DOWN,
        flap_position=FlapState.HALF,
        master_arm=MasterArmState.ARM,
        speed_brake=0.0,
        hook_position=False,
        hook_commanded_down=False,
        obogs_on=True,
        launch_bar_deployed=True,
        wing_fold_spread=True,
        takeoff_trim_confirmed=True,
        master_mode_combat=False,
        airborne=False,
        takeoff_sequence=True,
        carrier_launch_sequence=True,
        carrier_recovery=False,
        gear_commanded_down=True,
        refueling_probe=False,
    )
    result.canopy_state = tv(CanopyState.CLOSED)
    for name, value in changes.items():
        setattr(result, name, tv(value) if name != "flight_phase" else value)
    return result


def rule_by_id(rule_id: str):
    rules = declarative_fa18c_rules(
        FA18CRuleThresholds(
            after_liftoff_grace_seconds=0.0,
            configuration_timeout_seconds=0.0,
            probe_reminder_seconds=0.0,
            combat_config_seconds=0.0,
        )
    )
    return next(rule for rule in rules if rule.id == rule_id)


def activate_rule(rule_id: str, current: AircraftState):
    engine, history = engine_for([rule_by_id(rule_id)])
    evaluate(engine, history, current, 0.0)
    transitions = evaluate(engine, history, current, 10.0)
    assert transitions
    return engine, history, transitions[0]


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
        ground_speed=7.0,
        parking_brake=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, taxi, 0.0) == ()
    assert evaluate(engine, history, taxi, 2.0)[0].type is RuleTransitionType.ACTIVATED

    rolling_slowly = state(
        flight_phase=FlightPhase.TAXI,
        ground_speed=3.0,
        parking_brake=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, rolling_slowly, 3.0) == ()
    released = state(
        flight_phase=FlightPhase.TAXI,
        ground_speed=3.0,
        parking_brake=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, released, 4.0) == ()
    assert (
        evaluate(engine, history, released, 4.5)[0].type is RuleTransitionType.RESOLVED
    )


def test_taxi_light_rule_waits_for_sustained_taxi_and_resolves() -> None:
    engine, history = engine_for([TaxiLightOffRule()])
    taxi = state(
        flight_phase=FlightPhase.TAXI,
        ground_speed=7.0,
        taxi_light_on=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, taxi, 0.0) == ()
    assert evaluate(engine, history, taxi, 4.9) == ()
    activated = evaluate(engine, history, taxi, 5.0)
    assert activated[0].issue.message == "Taxi light is off."

    light_on = state(
        flight_phase=FlightPhase.TAXI,
        ground_speed=7.0,
        taxi_light_on=True,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, light_on, 6.0) == ()
    assert evaluate(engine, history, light_on, 6.5)[0].type is RuleTransitionType.RESOLVED


def test_taxi_light_rule_does_not_chatter_while_stopped() -> None:
    engine, history = engine_for([TaxiLightOffRule()])
    stopped = state(
        flight_phase=FlightPhase.STARTUP,
        ground_speed=0.0,
        taxi_light_on=False,
        weight_on_wheels=True,
    )
    assert evaluate(engine, history, stopped, 0.0) == ()
    assert evaluate(engine, history, stopped, 10.0) == ()


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


@pytest.mark.parametrize(
    ("rule_id", "invalid_changes", "valid_changes"),
    [
        (
            "CARRIER_FLAPS_NOT_HALF",
            {"flap_position": FlapState.AUTO},
            {"flap_position": FlapState.HALF},
        ),
        (
            "TAKEOFF_TRIM_NOT_CONFIRMED",
            {"takeoff_trim_confirmed": False},
            {"takeoff_trim_confirmed": True},
        ),
        (
            "WINGS_NOT_SPREAD_FOR_LAUNCH",
            {"wing_fold_spread": False},
            {"wing_fold_spread": True},
        ),
        (
            "SPEEDBRAKE_EXTENDED_FOR_LAUNCH",
            {"speed_brake": 0.5},
            {"speed_brake": 0.0},
        ),
        (
            "EJECTION_SEAT_SAFE_FOR_LAUNCH",
            {"ejection_seat_armed": False},
            {"ejection_seat_armed": True},
        ),
        ("OBOGS_OFF_FOR_TAKEOFF", {"obogs_on": False}, {"obogs_on": True}),
        (
            "LAUNCH_BAR_DOWN_AIRBORNE",
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "launch_bar_deployed": True,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "launch_bar_deployed": False,
                "carrier_launch_sequence": False,
            },
        ),
        (
            "FLAPS_NOT_AUTO_AFTER_TAKEOFF",
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "flap_position": FlapState.HALF,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "flap_position": FlapState.AUTO,
                "carrier_launch_sequence": False,
            },
        ),
        (
            "GEAR_STILL_DOWN_AFTER_TAKEOFF",
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "gear_position": GearState.DOWN,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.CLIMB,
                "airborne": True,
                "gear_position": GearState.UP,
                "carrier_launch_sequence": False,
            },
        ),
        (
            "HOOK_DOWN_OUTSIDE_RECOVERY",
            {
                "flight_phase": FlightPhase.CRUISE,
                "airborne": True,
                "hook_position": True,
                "carrier_recovery": False,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.CRUISE,
                "airborne": True,
                "hook_position": False,
                "carrier_recovery": False,
                "carrier_launch_sequence": False,
            },
        ),
        (
            "MASTER_ARM_SAFE_IN_COMBAT_MODE",
            {
                "master_mode_combat": True,
                "master_arm": MasterArmState.SAFE,
            },
            {
                "master_mode_combat": True,
                "master_arm": MasterArmState.ARM,
            },
        ),
        (
            "GEAR_COMMANDED_DOWN_BUT_NOT_SAFE",
            {"gear_commanded_down": True, "gear_position": GearState.TRANSIT},
            {"gear_commanded_down": True, "gear_position": GearState.DOWN},
        ),
        (
            "HOOK_COMMANDED_DOWN_BUT_NOT_EXTENDED",
            {"hook_commanded_down": True, "hook_position": False},
            {"hook_commanded_down": True, "hook_position": True},
        ),
        (
            "CARRIER_HOOK_NOT_DOWN",
            {
                "flight_phase": FlightPhase.APPROACH,
                "carrier_recovery": True,
                "gear_position": GearState.DOWN,
                "hook_position": False,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.APPROACH,
                "carrier_recovery": True,
                "gear_position": GearState.DOWN,
                "hook_position": True,
                "carrier_launch_sequence": False,
            },
        ),
        (
            "FLAPS_NOT_FULL_ON_CARRIER_RECOVERY",
            {
                "flight_phase": FlightPhase.APPROACH,
                "carrier_recovery": True,
                "gear_position": GearState.DOWN,
                "flap_position": FlapState.HALF,
                "carrier_launch_sequence": False,
            },
            {
                "flight_phase": FlightPhase.APPROACH,
                "carrier_recovery": True,
                "gear_position": GearState.DOWN,
                "flap_position": FlapState.FULL,
                "carrier_launch_sequence": False,
            },
        ),
    ],
)
def test_priority_declarative_rules_trigger_only_for_invalid_configuration(
    rule_id: str,
    invalid_changes: dict[str, object],
    valid_changes: dict[str, object],
) -> None:
    engine, history = engine_for([rule_by_id(rule_id)])
    assert evaluate(engine, history, rich_state(**valid_changes), 0.0) == ()

    invalid = rich_state(**invalid_changes)
    transitions = evaluate(engine, history, invalid, 1.0) + evaluate(
        engine, history, invalid, 11.0
    )
    activated = next(
        item for item in transitions if item.type is RuleTransitionType.ACTIVATED
    )
    assert activated.issue.rule_id == rule_id


def test_declarative_rule_respects_unavailable_telemetry_and_resolves() -> None:
    engine, history, activated = activate_rule(
        "CARRIER_FLAPS_NOT_HALF",
        rich_state(flap_position=FlapState.AUTO),
    )
    assert activated.notification_eligible

    unavailable = rich_state(flap_position=FlapState.AUTO)
    unavailable.flap_position = TelemetryValue.unavailable("test")
    disabled = evaluate(engine, history, unavailable, 11.1)
    assert disabled[0].type is RuleTransitionType.DISABLED

    engine, history, _ = activate_rule(
        "CARRIER_FLAPS_NOT_HALF",
        rich_state(flap_position=FlapState.AUTO),
    )
    corrected = rich_state(flap_position=FlapState.HALF)
    evaluate(engine, history, corrected, 12.0)
    resolved = evaluate(engine, history, corrected, 13.0)
    assert resolved[0].type is RuleTransitionType.RESOLVED


def test_declarative_rule_cooldown_suppresses_repeat_notification() -> None:
    engine, history, first = activate_rule(
        "CARRIER_FLAPS_NOT_HALF",
        rich_state(flap_position=FlapState.AUTO),
    )
    assert first.notification_eligible
    corrected = rich_state(flap_position=FlapState.HALF)
    evaluate(engine, history, corrected, 12.0)
    evaluate(engine, history, corrected, 13.0)
    invalid = rich_state(flap_position=FlapState.AUTO)
    evaluate(engine, history, invalid, 14.0)
    second = evaluate(engine, history, invalid, 15.0)[0]
    assert not second.notification_eligible


def test_phase_sensitive_declarative_rule_avoids_false_warning() -> None:
    rule = rule_by_id("FLAPS_NOT_AUTO_AFTER_TAKEOFF")
    engine, history = engine_for([rule])
    cruise = rich_state(
        flight_phase=FlightPhase.CRUISE,
        airborne=True,
        flap_position=FlapState.HALF,
        carrier_launch_sequence=False,
    )
    assert evaluate(engine, history, cruise, 0.0) == ()
    assert engine.active_issues == ()


def test_hook_extension_mismatch_is_silent_during_ground_start() -> None:
    rule = rule_by_id("HOOK_COMMANDED_DOWN_BUT_NOT_EXTENDED")
    engine, history = engine_for([rule])
    startup = rich_state(
        flight_phase=FlightPhase.STARTUP,
        hook_commanded_down=True,
        hook_position=False,
        carrier_launch_sequence=False,
    )
    assert evaluate(engine, history, startup, 0.0) == ()
    assert evaluate(engine, history, startup, 10.0) == ()


def test_runtime_registers_only_one_refueling_probe_reminder() -> None:
    assert [
        rule.id for rule in fa18c_rules() if "REFUEL" in rule.id and "PROBE" in rule.id
    ] == ["FA18_REFUELING_PROBE_LEFT_OUT"]
