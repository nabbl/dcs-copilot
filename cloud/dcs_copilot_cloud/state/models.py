"""Typed normalized state exposed to deterministic cloud layers."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class FlightPhase(StrEnum):
    UNKNOWN = "UNKNOWN"
    COLD_DARK = "COLD_DARK"
    STARTUP = "STARTUP"
    TAXI = "TAXI"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    COMBAT = "COMBAT"
    REFUELING = "REFUELING"
    APPROACH = "APPROACH"
    LANDING = "LANDING"
    POST_LANDING = "POST_LANDING"


class TelemetryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class GearState(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    TRANSIT = "TRANSIT"
    UNKNOWN = "UNKNOWN"


class FlapState(StrEnum):
    AUTO = "AUTO"
    HALF = "HALF"
    FULL = "FULL"
    UNKNOWN = "UNKNOWN"


class CanopyState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class MasterArmState(StrEnum):
    SAFE = "SAFE"
    ARM = "ARM"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TelemetryValue(Generic[T]):
    value: T | None = None
    available: bool = False
    updated_at: float | None = None
    source: str | None = None
    stale: bool = False

    @property
    def status(self) -> TelemetryStatus:
        if not self.available:
            return TelemetryStatus.UNAVAILABLE
        return TelemetryStatus.STALE if self.stale else TelemetryStatus.AVAILABLE

    @property
    def usable(self) -> bool:
        return self.available and not self.stale and self.value is not None

    @classmethod
    def unavailable(cls, source: str | None = None) -> TelemetryValue[T]:
        return cls(source=source)


def unavailable() -> TelemetryValue[Any]:
    return TelemetryValue.unavailable()


@dataclass(slots=True)
class AircraftState:
    aircraft: str | None = None
    connected: bool = False
    flight_phase: FlightPhase = FlightPhase.UNKNOWN

    indicated_airspeed: TelemetryValue[float] = field(default_factory=unavailable)
    ground_speed: TelemetryValue[float] = field(default_factory=unavailable)
    altitude_msl: TelemetryValue[float] = field(default_factory=unavailable)
    heading: TelemetryValue[float] = field(default_factory=unavailable)

    gear_position: TelemetryValue[GearState] = field(default_factory=unavailable)
    flap_position: TelemetryValue[FlapState] = field(default_factory=unavailable)
    canopy_state: TelemetryValue[CanopyState] = field(default_factory=unavailable)

    master_arm: TelemetryValue[MasterArmState] = field(default_factory=unavailable)
    selected_weapon: TelemetryValue[str] = field(default_factory=unavailable)
    fuel_quantity: TelemetryValue[float] = field(default_factory=unavailable)

    master_caution: TelemetryValue[bool] = field(default_factory=unavailable)
    warning_lights: dict[str, TelemetryValue[bool]] = field(default_factory=dict)

    parking_brake: TelemetryValue[bool] = field(default_factory=unavailable)
    battery_on: TelemetryValue[bool] = field(default_factory=unavailable)
    apu_ready: TelemetryValue[bool] = field(default_factory=unavailable)
    left_generator_normal: TelemetryValue[bool] = field(default_factory=unavailable)
    right_generator_normal: TelemetryValue[bool] = field(default_factory=unavailable)
    bleed_air_normal: TelemetryValue[bool] = field(default_factory=unavailable)
    ins_mode: TelemetryValue[str] = field(default_factory=unavailable)
    taxi_light_on: TelemetryValue[bool] = field(default_factory=unavailable)
    speed_brake: TelemetryValue[float] = field(default_factory=unavailable)
    refueling_probe: TelemetryValue[bool] = field(default_factory=unavailable)
    hook_position: TelemetryValue[bool] = field(default_factory=unavailable)
    hook_commanded_down: TelemetryValue[bool] = field(default_factory=unavailable)
    ejection_seat_armed: TelemetryValue[bool] = field(default_factory=unavailable)
    obogs_on: TelemetryValue[bool] = field(default_factory=unavailable)

    weight_on_wheels: TelemetryValue[bool] = field(default_factory=unavailable)
    engine_rpm_left: TelemetryValue[float] = field(default_factory=unavailable)
    engine_rpm_right: TelemetryValue[float] = field(default_factory=unavailable)
    throttle_left: TelemetryValue[float] = field(default_factory=unavailable)
    throttle_right: TelemetryValue[float] = field(default_factory=unavailable)

    gear_commanded_down: TelemetryValue[bool] = field(default_factory=unavailable)
    launch_bar_deployed: TelemetryValue[bool] = field(default_factory=unavailable)
    wing_fold_spread: TelemetryValue[bool] = field(default_factory=unavailable)
    takeoff_trim_pressed: TelemetryValue[bool] = field(default_factory=unavailable)
    takeoff_trim_confirmed: TelemetryValue[bool] = field(default_factory=unavailable)
    master_mode_combat: TelemetryValue[bool] = field(default_factory=unavailable)

    airborne: TelemetryValue[bool] = field(default_factory=unavailable)
    takeoff_sequence: TelemetryValue[bool] = field(default_factory=unavailable)
    carrier_launch_sequence: TelemetryValue[bool] = field(default_factory=unavailable)
    carrier_recovery: TelemetryValue[bool] = field(default_factory=unavailable)

    raw: dict[str, TelemetryValue[Any]] = field(default_factory=dict)

    def telemetry(self) -> dict[str, TelemetryValue[Any]]:
        result: dict[str, TelemetryValue[Any]] = {}
        for model_field in fields(self):
            value = getattr(self, model_field.name)
            if isinstance(value, TelemetryValue):
                result[model_field.name] = value
        for name, value in self.warning_lights.items():
            result[f"warning_lights.{name}"] = value
        return result

    @property
    def available_field_count(self) -> int:
        return sum(value.usable for value in self.telemetry().values())

    @property
    def unavailable_field_count(self) -> int:
        return sum(not value.usable for value in self.telemetry().values())


@dataclass(slots=True)
class PartialAircraftState:
    values: dict[str, TelemetryValue[Any]] = field(default_factory=dict)
    warning_lights: dict[str, TelemetryValue[bool]] = field(default_factory=dict)
    raw: dict[str, TelemetryValue[Any]] = field(default_factory=dict)

    def apply_to(self, state: AircraftState) -> None:
        for name, value in self.values.items():
            if not hasattr(state, name):
                raise ValueError(f"unknown normalized aircraft field: {name}")
            setattr(state, name, value)
        state.warning_lights.update(self.warning_lights)
        state.raw.update(self.raw)
