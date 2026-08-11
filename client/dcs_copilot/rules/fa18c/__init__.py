"""Verified, conservative F/A-18C configuration rules."""

from __future__ import annotations

from dataclasses import dataclass

from dcs_copilot.state.models import (
    CanopyState,
    FlapState,
    FlightPhase,
    GearState,
    MasterArmState,
)

from ..base import CopilotMode, Rule, RuleContext, RuleResult, Severity
from ..declarative import DeclarativeRule, RuleDefinition

HORNET = frozenset({"FA-18C_hornet"})
AIRBORNE_PHASES = frozenset(
    {
        FlightPhase.TAKEOFF,
        FlightPhase.CLIMB,
        FlightPhase.CRUISE,
        FlightPhase.COMBAT,
        FlightPhase.REFUELING,
        FlightPhase.APPROACH,
        FlightPhase.LANDING,
    }
)


@dataclass(frozen=True, slots=True)
class FA18CRuleThresholds:
    after_liftoff_grace_seconds: float = 5.0
    configuration_timeout_seconds: float = 3.0
    probe_reminder_seconds: float = 2.0
    combat_config_seconds: float = 2.0
    speedbrake_extended_threshold: float = 0.05


def _number(context: RuleContext, field: str) -> float:
    telemetry = context.telemetry(field)
    assert telemetry is not None and telemetry.usable
    assert telemetry.value is not None
    return float(telemetry.value)


def _boolean(context: RuleContext, field: str) -> bool:
    telemetry = context.telemetry(field)
    assert telemetry is not None and telemetry.usable
    return bool(telemetry.value)


class MasterCautionRule(Rule):
    id = "FA18_MASTER_CAUTION"
    severity = Severity.WARNING
    cooldown_seconds = 30.0
    required_fields = frozenset({"master_caution"})
    aircraft_names = HORNET
    debounce_on_seconds = 0.25
    debounce_off_seconds = 0.5

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if not _boolean(context, "master_caution"):
            return None
        active_warnings = sorted(
            name
            for name, light in context.state.warning_lights.items()
            if light.usable and light.value
        )
        return RuleResult(
            message="Master Caution is on.",
            explanation=("The Hornet's exported Master Caution light is illuminated."),
            data={"active_warning_lights": active_warnings},
        )


class GearOverspeedRule(Rule):
    id = "FA18_GEAR_OVERSPEED"
    severity = Severity.WARNING
    cooldown_seconds = 30.0
    required_fields = frozenset(
        {"indicated_airspeed", "gear_position", "weight_on_wheels"}
    )
    aircraft_names = HORNET
    debounce_on_seconds = 1.0
    debounce_off_seconds = 1.0

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        speed = _number(context, "indicated_airspeed")
        wow = _boolean(context, "weight_on_wheels")
        gear = context.state.gear_position.value
        threshold = 240.0 if context.active else 250.0
        if wow or gear not in {GearState.DOWN, GearState.TRANSIT} or speed < threshold:
            return None
        return RuleResult(
            message="Gear is still down after reaching 250 knots.",
            explanation=(
                "The aircraft is airborne at or above the Hornet landing-gear "
                "extension speed with the gear down or in transit."
            ),
            data={"ias_knots": round(speed, 1), "gear": str(gear)},
        )


class CanopyOpenWhileMovingRule(Rule):
    id = "FA18_CANOPY_OPEN_MOVING"
    severity = Severity.WARNING
    cooldown_seconds = 30.0
    required_fields = frozenset({"canopy_state", "indicated_airspeed"})
    aircraft_names = HORNET
    debounce_on_seconds = 1.0
    debounce_off_seconds = 0.5

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        speed = _number(context, "indicated_airspeed")
        canopy = context.state.canopy_state.value
        speed_threshold = 10.0 if context.active else 20.0
        if canopy is CanopyState.CLOSED or speed < speed_threshold:
            return None
        return RuleResult(
            message="Canopy is not closed while the aircraft is moving.",
            explanation=(
                "The exported canopy position is open or moving while indicated "
                "airspeed is above the ground-movement threshold."
            ),
            data={"ias_knots": round(speed, 1), "canopy": str(canopy)},
        )


class ParkingBrakeTaxiRule(Rule):
    id = "FA18_PARKING_BRAKE_TAXI"
    severity = Severity.ADVISORY
    cooldown_seconds = 45.0
    required_fields = frozenset(
        {"parking_brake", "indicated_airspeed", "weight_on_wheels"}
    )
    aircraft_names = HORNET
    debounce_on_seconds = 2.0
    debounce_off_seconds = 0.5

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        speed = _number(context, "indicated_airspeed")
        minimum_speed = 2.0 if context.active else 5.0
        if (
            not _boolean(context, "weight_on_wheels")
            or not _boolean(context, "parking_brake")
            or speed < minimum_speed
        ):
            return None
        return RuleResult(
            message="Parking brake is still engaged while taxiing.",
            explanation=(
                "Weight is on the wheels, the parking brake is engaged, and the "
                "aircraft is moving."
            ),
            data={"ias_knots": round(speed, 1)},
        )


class TaxiLightOffRule(Rule):
    id = "FA18_TAXI_LIGHT_OFF"
    category = "best_practice"
    minimum_mode = CopilotMode.NORMAL
    severity = Severity.ADVISORY
    cooldown_seconds = 120.0
    required_fields = frozenset(
        {"taxi_light_on", "indicated_airspeed", "weight_on_wheels"}
    )
    aircraft_names = HORNET
    flight_phases = frozenset({FlightPhase.TAXI})
    debounce_on_seconds = 5.0
    debounce_off_seconds = 0.5
    description = "Remind the pilot to use the taxi light while rolling."
    source_reference = "DCS-BIOS FA-18C_hornet/LDG_TAXI_SW"

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if (
            not _boolean(context, "weight_on_wheels")
            or _boolean(context, "taxi_light_on")
            or _number(context, "indicated_airspeed") < 3.0
        ):
            return None
        return RuleResult(
            message="Taxi light is off.",
            explanation=(
                "The aircraft is rolling in the taxi phase with the landing/taxi "
                "light switch off."
            ),
            data={"ias_knots": round(_number(context, "indicated_airspeed"), 1)},
        )


class EjectionSeatNotArmedRule(Rule):
    id = "FA18_EJECTION_SEAT_NOT_ARMED"
    severity = Severity.WARNING
    cooldown_seconds = 120.0
    required_fields = frozenset({"ejection_seat_armed"})
    aircraft_names = HORNET
    flight_phases = frozenset({FlightPhase.TAXI}) | AIRBORNE_PHASES
    debounce_on_seconds = 2.0
    debounce_off_seconds = 0.25

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if _boolean(context, "ejection_seat_armed"):
            return None
        return RuleResult(
            message="Ejection seat is not armed.",
            explanation=(
                "The Hornet ejection-seat handle is SAFE while the aircraft is "
                "taxiing or airborne."
            ),
            data={"flight_phase": context.state.flight_phase.value},
        )


class RefuelingProbeLeftOutRule(Rule):
    id = "FA18_REFUELING_PROBE_LEFT_OUT"
    severity = Severity.ADVISORY
    cooldown_seconds = 60.0
    required_fields = frozenset({"refueling_probe"})
    aircraft_names = HORNET
    flight_phases = frozenset(
        {
            FlightPhase.CLIMB,
            FlightPhase.CRUISE,
            FlightPhase.COMBAT,
            FlightPhase.APPROACH,
            FlightPhase.LANDING,
        }
    )
    debounce_on_seconds = 2.0
    debounce_off_seconds = 0.25

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if not _boolean(context, "refueling_probe"):
            return None
        return RuleResult(
            message="Refueling probe is still out.",
            explanation=(
                "The Hornet refueling probe remains extended outside the "
                "detected refueling phase."
            ),
            data={"flight_phase": context.state.flight_phase.value},
        )


def fa18c_rule_definitions(
    thresholds: FA18CRuleThresholds | None = None,
) -> tuple[RuleDefinition, ...]:
    config = thresholds or FA18CRuleThresholds()
    takeoff_phases = frozenset({FlightPhase.TAXI, FlightPhase.TAKEOFF})
    return (
        RuleDefinition(
            id="CARRIER_FLAPS_NOT_HALF",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=takeoff_phases,
            required_fields=frozenset({"carrier_launch_sequence", "flap_position"}),
            condition={
                "all": [
                    {"carrier_launch_sequence": True},
                    {"flap_position": {"not_equals": FlapState.HALF}},
                ]
            },
            activation_delay=0.25,
            resolution_delay=0.25,
            cooldown=30.0,
            message="Flaps — HALF.",
            explanation="The jet is in a carrier launch sequence and the flap switch is not HALF.",
            data_fields=frozenset({"flap_position"}),
        ),
        RuleDefinition(
            id="TAKEOFF_TRIM_NOT_CONFIRMED",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=takeoff_phases,
            required_fields=frozenset(
                {"carrier_launch_sequence", "takeoff_trim_confirmed"}
            ),
            condition={
                "all": [
                    {"carrier_launch_sequence": True},
                    {"takeoff_trim_confirmed": False},
                ]
            },
            activation_delay=0.25,
            resolution_delay=0.25,
            cooldown=30.0,
            message="Takeoff trim not confirmed.",
            explanation=(
                "The T/O TRIM button has not been observed since startup or the last "
                "landing. Actual stabilator trim verification is unsupported unless "
                "reliable IC-safe telemetry is available."
            ),
            data_fields=frozenset({"takeoff_trim_confirmed"}),
        ),
        RuleDefinition(
            id="WINGS_NOT_SPREAD_FOR_LAUNCH",
            aircraft="FA-18C_hornet",
            severity=Severity.CRITICAL,
            phases=takeoff_phases,
            required_fields=frozenset({"carrier_launch_sequence", "wing_fold_spread"}),
            condition={
                "all": [
                    {"carrier_launch_sequence": True},
                    {"wing_fold_spread": False},
                ]
            },
            activation_delay=0.25,
            resolution_delay=0.25,
            cooldown=30.0,
            message="Wings.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="The external wing-fold position is not fully spread for launch.",
            data_fields=frozenset({"wing_fold_spread"}),
        ),
        RuleDefinition(
            id="SPEEDBRAKE_EXTENDED_FOR_LAUNCH",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=takeoff_phases,
            required_fields=frozenset({"carrier_launch_sequence", "speed_brake"}),
            condition={
                "all": [
                    {"carrier_launch_sequence": True},
                    {
                        "speed_brake": {
                            "greater_than": config.speedbrake_extended_threshold
                        }
                    },
                ]
            },
            activation_delay=0.25,
            resolution_delay=0.25,
            cooldown=30.0,
            message="Speedbrake.",
            explanation="The speedbrake is extended during the carrier launch sequence.",
            data_fields=frozenset({"speed_brake"}),
        ),
        RuleDefinition(
            id="EJECTION_SEAT_SAFE_FOR_LAUNCH",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=takeoff_phases,
            required_fields=frozenset({"takeoff_sequence", "ejection_seat_armed"}),
            condition={
                "all": [
                    {"takeoff_sequence": True},
                    {"ejection_seat_armed": False},
                ]
            },
            activation_delay=0.5,
            resolution_delay=0.25,
            cooldown=60.0,
            message="Seat.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="The ejection seat is SAFE during the takeoff sequence.",
            data_fields=frozenset({"ejection_seat_armed"}),
        ),
        RuleDefinition(
            id="OBOGS_OFF_FOR_TAKEOFF",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=takeoff_phases,
            required_fields=frozenset({"takeoff_sequence", "obogs_on"}),
            condition={
                "all": [
                    {"takeoff_sequence": True},
                    {"obogs_on": False},
                ]
            },
            activation_delay=0.5,
            resolution_delay=0.25,
            cooldown=60.0,
            message="Oxygen.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="OBOGS is off during the takeoff sequence.",
            data_fields=frozenset({"obogs_on"}),
        ),
        RuleDefinition(
            id="LAUNCH_BAR_DOWN_AIRBORNE",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            required_fields=frozenset({"airborne", "launch_bar_deployed"}),
            condition={
                "all": [
                    {"airborne": True},
                    {"launch_bar_deployed": True},
                ]
            },
            activation_delay=config.after_liftoff_grace_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Launch bar.",
            explanation="The launch bar is still commanded down after liftoff.",
            data_fields=frozenset({"launch_bar_deployed"}),
        ),
        RuleDefinition(
            id="FLAPS_NOT_AUTO_AFTER_TAKEOFF",
            aircraft="FA-18C_hornet",
            severity=Severity.ADVISORY,
            phases=frozenset({FlightPhase.CLIMB}),
            required_fields=frozenset({"airborne", "flap_position"}),
            condition={
                "all": [
                    {"airborne": True},
                    {"flap_position": {"not_equals": FlapState.AUTO}},
                ]
            },
            activation_delay=config.after_liftoff_grace_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Flaps.",
            explanation="The aircraft is climbing and the flap switch is not AUTO.",
            data_fields=frozenset({"flap_position"}),
        ),
        RuleDefinition(
            id="GEAR_STILL_DOWN_AFTER_TAKEOFF",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=frozenset({FlightPhase.TAKEOFF, FlightPhase.CLIMB}),
            required_fields=frozenset({"airborne", "gear_position"}),
            condition={
                "all": [
                    {"airborne": True},
                    {"gear_position": {"not_equals": GearState.UP}},
                ]
            },
            activation_delay=config.after_liftoff_grace_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Gear.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="The aircraft is airborne and the gear is not up after the liftoff grace period.",
            data_fields=frozenset({"gear_position"}),
        ),
        RuleDefinition(
            id="HOOK_DOWN_OUTSIDE_RECOVERY",
            aircraft="FA-18C_hornet",
            severity=Severity.ADVISORY,
            required_fields=frozenset({"airborne", "carrier_recovery", "hook_position"}),
            condition={
                "all": [
                    {"airborne": True},
                    {"carrier_recovery": False},
                    {"hook_position": True},
                ]
            },
            activation_delay=1.0,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Hook is down outside carrier recovery.",
            proactive=False,
            explanation="The hook is physically down while airborne outside a detected recovery context.",
            data_fields=frozenset({"hook_position", "carrier_recovery"}),
        ),
        RuleDefinition(
            id="MASTER_ARM_SAFE_IN_COMBAT_MODE",
            aircraft="FA-18C_hornet",
            severity=Severity.ADVISORY,
            required_fields=frozenset({"master_mode_combat", "master_arm"}),
            condition={
                "all": [
                    {"master_mode_combat": True},
                    {"master_arm": MasterArmState.SAFE},
                ]
            },
            activation_delay=config.combat_config_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Master Arm is safe.",
            explanation="A/A or A/G master mode is selected while Master Arm is SAFE.",
            data_fields=frozenset({"master_arm", "master_mode_combat"}),
        ),
        RuleDefinition(
            id="GEAR_COMMANDED_DOWN_BUT_NOT_SAFE",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            required_fields=frozenset({"gear_commanded_down", "gear_position"}),
            condition={
                "all": [
                    {"gear_commanded_down": True},
                    {"gear_position": {"not_equals": GearState.DOWN}},
                ]
            },
            activation_delay=config.configuration_timeout_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Gear isn't showing safe.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="The gear lever is down but the three gear-safe lights do not indicate down and locked.",
            data_fields=frozenset({"gear_position", "gear_commanded_down"}),
        ),
        RuleDefinition(
            id="HOOK_COMMANDED_DOWN_BUT_NOT_EXTENDED",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=frozenset(
                {
                    FlightPhase.TAKEOFF,
                    FlightPhase.CLIMB,
                    FlightPhase.CRUISE,
                    FlightPhase.COMBAT,
                    FlightPhase.REFUELING,
                }
            ),
            required_fields=frozenset({"hook_commanded_down", "hook_position"}),
            condition={
                "all": [
                    {"hook_commanded_down": True},
                    {"hook_position": False},
                ]
            },
            activation_delay=config.configuration_timeout_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Hook lever is down, but the hook has not extended.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="The hook lever is down but the external hook position has not reached down.",
            data_fields=frozenset({"hook_position", "hook_commanded_down"}),
        ),
        RuleDefinition(
            id="CARRIER_HOOK_NOT_DOWN",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=frozenset({FlightPhase.APPROACH, FlightPhase.LANDING}),
            required_fields=frozenset(
                {"carrier_recovery", "gear_position", "hook_position"}
            ),
            condition={
                "all": [
                    {"carrier_recovery": True},
                    {"gear_position": GearState.DOWN},
                    {"hook_position": False},
                ]
            },
            activation_delay=config.configuration_timeout_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Hook is not down for carrier recovery.",
            minimum_mode=CopilotMode.MINIMAL,
            explanation="Carrier recovery is detected with landing gear down and the hook is not physically down.",
            data_fields=frozenset({"gear_position", "hook_position"}),
        ),
        RuleDefinition(
            id="FLAPS_NOT_FULL_ON_CARRIER_RECOVERY",
            aircraft="FA-18C_hornet",
            severity=Severity.WARNING,
            phases=frozenset({FlightPhase.APPROACH, FlightPhase.LANDING}),
            required_fields=frozenset(
                {"carrier_recovery", "gear_position", "flap_position"}
            ),
            condition={
                "all": [
                    {"carrier_recovery": True},
                    {"gear_position": GearState.DOWN},
                    {"flap_position": {"not_equals": FlapState.FULL}},
                ]
            },
            activation_delay=config.configuration_timeout_seconds,
            resolution_delay=0.25,
            cooldown=45.0,
            message="Flaps — FULL.",
            explanation="Carrier recovery is detected with gear down and flaps not FULL.",
            data_fields=frozenset({"gear_position", "flap_position"}),
        ),
    )


def declarative_fa18c_rules(
    thresholds: FA18CRuleThresholds | None = None,
) -> tuple[DeclarativeRule, ...]:
    return tuple(DeclarativeRule(definition) for definition in fa18c_rule_definitions(thresholds))


def fa18c_rules() -> tuple[Rule, ...]:
    return (
        *declarative_fa18c_rules(),
        MasterCautionRule(),
        GearOverspeedRule(),
        CanopyOpenWhileMovingRule(),
        ParkingBrakeTaxiRule(),
        TaxiLightOffRule(),
        EjectionSeatNotArmedRule(),
        RefuelingProbeLeftOutRule(),
    )


__all__ = [
    "FA18CRuleThresholds",
    "CanopyOpenWhileMovingRule",
    "DeclarativeRule",
    "EjectionSeatNotArmedRule",
    "GearOverspeedRule",
    "MasterCautionRule",
    "ParkingBrakeTaxiRule",
    "TaxiLightOffRule",
    "RefuelingProbeLeftOutRule",
    "declarative_fa18c_rules",
    "fa18c_rule_definitions",
    "fa18c_rules",
]
