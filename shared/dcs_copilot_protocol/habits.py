"""Versioned, bounded end-of-flight semantic statistics."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .messages import ControlMessage, ProtocolError

FLIGHT_SUMMARY_VERSION = 1
MAX_SUMMARY_RULES = 32
MAX_RULE_ACTIVATIONS = 100
HABIT_RULE_IDS = frozenset(
    {
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
    }
)


class FlightSummaryProtocolError(ProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class FlightSummary:
    summary_id: str
    aircraft: str
    rule_activations: dict[str, int]
    summary_version: int = FLIGHT_SUMMARY_VERSION

    def __post_init__(self) -> None:
        if self.summary_version != FLIGHT_SUMMARY_VERSION:
            raise FlightSummaryProtocolError("unsupported flight summary version")
        try:
            UUID(self.summary_id)
        except (ValueError, TypeError) as exc:
            raise FlightSummaryProtocolError(
                "summary_id must be a UUID"
            ) from exc
        if not isinstance(self.aircraft, str):
            raise FlightSummaryProtocolError("aircraft must be a string")
        if not self.aircraft.strip() or len(self.aircraft) > 64:
            raise FlightSummaryProtocolError(
                "aircraft must contain 1 to 64 characters"
            )
        if not isinstance(self.rule_activations, dict):
            raise FlightSummaryProtocolError("rules must be an object")
        if len(self.rule_activations) > MAX_SUMMARY_RULES:
            raise FlightSummaryProtocolError(
                f"flight summary accepts at most {MAX_SUMMARY_RULES} rules"
            )
        unknown = set(self.rule_activations) - HABIT_RULE_IDS
        if unknown:
            raise FlightSummaryProtocolError(
                f"flight summary rule is not allowlisted: {', '.join(sorted(unknown))}"
            )
        for rule_id, activations in self.rule_activations.items():
            if not isinstance(rule_id, str):
                raise FlightSummaryProtocolError("flight summary rule IDs must be strings")
            if (
                not isinstance(activations, int)
                or isinstance(activations, bool)
                or not 0 <= activations <= MAX_RULE_ACTIVATIONS
            ):
                raise FlightSummaryProtocolError(
                    f"{rule_id} activations must be between 0 and "
                    f"{MAX_RULE_ACTIVATIONS}"
                )
        object.__setattr__(self, "rule_activations", self.rule_activations.copy())

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "flight.summary",
            {
                "summary_version": self.summary_version,
                "summary_id": self.summary_id,
                "aircraft": self.aircraft.strip(),
                "rules": dict(sorted(self.rule_activations.items())),
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> FlightSummary:
        if message.type != "flight.summary":
            raise FlightSummaryProtocolError("expected flight.summary")
        if set(message.payload) != {
            "summary_version",
            "summary_id",
            "aircraft",
            "rules",
        }:
            raise FlightSummaryProtocolError(
                "flight.summary payload has unexpected fields"
            )
        version = message.payload["summary_version"]
        summary_id = message.payload["summary_id"]
        aircraft = message.payload["aircraft"]
        rules = message.payload["rules"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise FlightSummaryProtocolError("summary_version must be an integer")
        if not isinstance(summary_id, str):
            raise FlightSummaryProtocolError("summary_id must be a string")
        if not isinstance(aircraft, str):
            raise FlightSummaryProtocolError("aircraft must be a string")
        if not isinstance(rules, dict):
            raise FlightSummaryProtocolError("rules must be an object")
        if any(not isinstance(key, str) for key in rules):
            raise FlightSummaryProtocolError("flight summary rule IDs must be strings")
        return cls(summary_id, aircraft, rules.copy(), version)
