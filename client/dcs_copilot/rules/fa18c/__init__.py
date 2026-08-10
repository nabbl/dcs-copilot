"""Verified, conservative F/A-18C configuration rules."""

from __future__ import annotations

from dcs_copilot.state.models import CanopyState, FlightPhase, GearState

from ..base import Rule, RuleContext, RuleResult, Severity

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


def fa18c_rules() -> tuple[Rule, ...]:
    return (
        MasterCautionRule(),
        GearOverspeedRule(),
        CanopyOpenWhileMovingRule(),
        ParkingBrakeTaxiRule(),
        EjectionSeatNotArmedRule(),
        RefuelingProbeLeftOutRule(),
    )


__all__ = [
    "CanopyOpenWhileMovingRule",
    "EjectionSeatNotArmedRule",
    "GearOverspeedRule",
    "MasterCautionRule",
    "ParkingBrakeTaxiRule",
    "RefuelingProbeLeftOutRule",
    "fa18c_rules",
]
