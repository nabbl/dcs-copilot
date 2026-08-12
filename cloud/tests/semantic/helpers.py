"""Shared helpers for backend semantic engine tests."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.fa18c import MODULE
from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey, RawTelemetryStore

FRACTION_IDENTIFIERS = {
    "CANOPY_POS",
    "EXT_SPEED_BRAKE",
    "EXT_REFUEL_PROBE",
    "EXT_HOOK",
    "EXT_WING_FOLDING",
    "INT_THROTTLE_LEFT",
    "INT_THROTTLE_RIGHT",
}


def set_int(raw: RawTelemetryStore, identifier: str, value: int, *, now: float) -> None:
    raw.update(RawTelemetryKey(MODULE, identifier, "integer", 0), value, received_at=now)


def set_str(raw: RawTelemetryStore, identifier: str, value: str, *, now: float) -> None:
    raw.update(RawTelemetryKey(MODULE, identifier, "string", 0), value, received_at=now)


def minimal_wow_grounded(raw: RawTelemetryStore, *, now: float) -> None:
    """Set weight-on-wheels sensors so the aircraft reads as grounded."""
    set_int(raw, "EXT_WOW_NOSE", 1, now=now)
    set_int(raw, "EXT_WOW_LEFT", 1, now=now)
    set_int(raw, "EXT_WOW_RIGHT", 1, now=now)


def minimal_gear_down(raw: RawTelemetryStore, *, now: float) -> None:
    set_int(raw, "GEAR_LEVER", 1, now=now)
    set_int(raw, "FLP_LG_NOSE_GEAR_LT", 1, now=now)
    set_int(raw, "FLP_LG_LEFT_GEAR_LT", 1, now=now)
    set_int(raw, "FLP_LG_RIGHT_GEAR_LT", 1, now=now)
