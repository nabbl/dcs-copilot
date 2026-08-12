"""Cloud-domain habit tracking models, independent of shared protocol."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

HABIT_RULE_IDS = frozenset({
    "FA18_MASTER_CAUTION",
    "FA18_GEAR_OVERSPEED",
    "FA18_CANOPY_OPEN_MOVING",
    "FA18_PARKING_BRAKE_TAXI",
    "FA18_TAXI_LIGHT_OFF",
    "FA18_EJECTION_SEAT_NOT_ARMED",
    "FA18_REFUELING_PROBE_LEFT_OUT",
    "CARRIER_FLAPS_NOT_HALF",
    "TAKEOFF_TRIM_NOT_CONFIRMED",
    "WINGS_NOT_SPREAD_FOR_LAUNCH",
    "SPEEDBRAKE_EXTENDED_FOR_LAUNCH",
    "EJECTION_SEAT_SAFE_FOR_LAUNCH",
    "OBOGS_OFF_FOR_TAKEOFF",
    "LAUNCH_BAR_DOWN_AIRBORNE",
    "FLAPS_NOT_AUTO_AFTER_TAKEOFF",
    "GEAR_STILL_DOWN_AFTER_TAKEOFF",
    "HOOK_DOWN_OUTSIDE_RECOVERY",
    "REFUEL_PROBE_LEFT_OUT",
    "MASTER_ARM_SAFE_IN_COMBAT_MODE",
    "GEAR_COMMANDED_DOWN_BUT_NOT_SAFE",
    "HOOK_COMMANDED_DOWN_BUT_NOT_EXTENDED",
    "CARRIER_HOOK_NOT_DOWN",
    "FLAPS_NOT_FULL_ON_CARRIER_RECOVERY",
})

MAX_SUMMARY_RULES = 32
MAX_RULE_ACTIVATIONS = 100


@dataclass(frozen=True, slots=True)
class FlightSummary:
    summary_id: str
    aircraft: str
    rule_activations: dict[str, int]

    def __post_init__(self) -> None:
        try:
            UUID(self.summary_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("summary_id must be a UUID") from exc
        if not self.aircraft.strip() or len(self.aircraft) > 64:
            raise ValueError("aircraft must contain 1-64 characters")
        if len(self.rule_activations) > MAX_SUMMARY_RULES:
            raise ValueError(f"flight summary accepts at most {MAX_SUMMARY_RULES} rules")
        unknown = set(self.rule_activations) - HABIT_RULE_IDS
        if unknown:
            raise ValueError(f"flight summary rule not allowlisted: {', '.join(sorted(unknown))}")
        for rule_id, activations in self.rule_activations.items():
            if not (0 <= activations <= MAX_RULE_ACTIVATIONS):
                raise ValueError(f"{rule_id} activations must be 0-{MAX_RULE_ACTIVATIONS}")
        object.__setattr__(self, "rule_activations", dict(self.rule_activations))
