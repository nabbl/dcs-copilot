"""Verified F/A-18C Hornet normalization adapter."""

from __future__ import annotations

from typing import Any

from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import (
    CanopyState,
    FlapState,
    GearState,
    MasterArmState,
    PartialAircraftState,
    TelemetryValue,
)

from .base import ControlReader, combine_values, map_value, parse_number
from .generic import GenericAircraftAdapter

MODULE = "FA-18C_hornet"

WARNING_LIGHTS = {
    "check_seat": "CLIP_CK_SEAT_LT",
    "apu_accumulator": "CLIP_APU_ACC_LT",
    "battery_switch": "CLIP_BATT_SW_LT",
    "fcs_hot": "CLIP_FCS_HOT_LT",
    "generator_tie": "CLIP_GEN_TIE_LT",
    "fuel_low": "CLIP_FUEL_LO_LT",
    "fces": "CLIP_FCES_LT",
    "left_generator": "CLIP_L_GEN_LT",
    "right_generator": "CLIP_R_GEN_LT",
}


class FA18CAdapter:
    def __init__(self, registry: DcsBiosControlRegistry) -> None:
        self.aircraft_names = {"FA-18C_hornet"}
        self.registry = registry
        self.generic = GenericAircraftAdapter(registry)
        self.gear_up_dwell_seconds = 3.0
        self._gear_up_candidate_since: float | None = None

    def normalize(
        self,
        bios_state: DcsBiosState,
        *,
        now: float,
        stale_timeout: float,
    ) -> PartialAircraftState:
        result = self.generic.normalize(
            bios_state, now=now, stale_timeout=stale_timeout
        )
        reader = ControlReader(
            self.registry, bios_state, now=now, stale_timeout=stale_timeout
        )
        raw: dict[str, TelemetryValue[Any]] = {}

        def read_int(identifier: str) -> TelemetryValue[Any]:
            value = reader.read(MODULE, identifier, output_type="integer")
            raw[identifier] = value
            return value

        gear_lever = read_int("GEAR_LEVER")
        gear_lights = [
            read_int("FLP_LG_NOSE_GEAR_LT"),
            read_int("FLP_LG_LEFT_GEAR_LT"),
            read_int("FLP_LG_RIGHT_GEAR_LT"),
        ]
        gear_value = self._gear_state(gear_lever, gear_lights, now=now)
        gear_position = combine_values(
            [gear_lever, *gear_lights],
            gear_value,
            "DCS-BIOS:FA-18C_hornet/gear-composite",
        )

        wow_values = [
            read_int("EXT_WOW_NOSE"),
            read_int("EXT_WOW_LEFT"),
            read_int("EXT_WOW_RIGHT"),
        ]
        wow = combine_values(
            wow_values,
            any(bool(item.value) for item in wow_values)
            if all(item.usable for item in wow_values)
            else None,
            "DCS-BIOS:FA-18C_hornet/WOW-composite",
        )

        flap = reader.read(
            MODULE,
            "FLAP_SW",
            map_value({0: FlapState.AUTO, 1: FlapState.HALF, 2: FlapState.FULL}),
            output_type="integer",
        )
        raw["FLAP_SW"] = flap

        canopy_fraction = reader.fraction(MODULE, "CANOPY_POS")
        raw["CANOPY_POS"] = canopy_fraction
        canopy = self._map_canopy(canopy_fraction)

        master_arm = reader.read(
            MODULE,
            "MASTER_ARM_SW",
            map_value({0: MasterArmState.SAFE, 1: MasterArmState.ARM}),
            output_type="integer",
        )
        raw["MASTER_ARM_SW"] = master_arm

        fuel_upper = reader.read(
            MODULE, "IFEI_FUEL_UP", parse_number, output_type="string"
        )
        fuel_legend = reader.read(MODULE, "IFEI_T", output_type="string")
        raw["IFEI_FUEL_UP"] = fuel_upper
        raw["IFEI_T"] = fuel_legend
        fuel = combine_values(
            [fuel_upper, fuel_legend],
            float(fuel_upper.value)
            if fuel_upper.usable
            and fuel_upper.value is not None
            and fuel_legend.usable
            and str(fuel_legend.value).strip() == "T"
            else None,
            "DCS-BIOS:FA-18C_hornet/IFEI-total-fuel",
        )

        parking_raw = read_int("EMERGENCY_PARKING_BRAKE_ROTATE")
        parking = self._map_bool(parking_raw, lambda value: value != 2)

        speed_brake = reader.fraction(MODULE, "EXT_SPEED_BRAKE")
        raw["EXT_SPEED_BRAKE"] = speed_brake
        probe_raw = reader.fraction(MODULE, "EXT_REFUEL_PROBE")
        raw["EXT_REFUEL_PROBE"] = probe_raw
        probe = self._map_bool(probe_raw, lambda value: value > 0.1)
        hook_raw = reader.fraction(MODULE, "EXT_HOOK")
        raw["EXT_HOOK"] = hook_raw
        hook = self._map_bool(hook_raw, lambda value: value > 0.5)

        seat_raw = read_int("EJECTION_SEAT_ARMED")
        seat = self._map_bool(seat_raw, bool)

        rpm_left = reader.read(MODULE, "IFEI_RPM_L", parse_number, output_type="string")
        rpm_right = reader.read(
            MODULE, "IFEI_RPM_R", parse_number, output_type="string"
        )
        raw["IFEI_RPM_L"] = rpm_left
        raw["IFEI_RPM_R"] = rpm_right
        throttle_left = reader.fraction(MODULE, "INT_THROTTLE_LEFT")
        throttle_right = reader.fraction(MODULE, "INT_THROTTLE_RIGHT")
        raw["INT_THROTTLE_LEFT"] = throttle_left
        raw["INT_THROTTLE_RIGHT"] = throttle_right

        master_caution_raw = read_int("MASTER_CAUTION_LT")
        master_caution = self._map_bool(master_caution_raw, bool)
        warning_lights: dict[str, TelemetryValue[bool]] = {}
        for semantic_name, identifier in WARNING_LIGHTS.items():
            warning_lights[semantic_name] = self._map_bool(read_int(identifier), bool)

        result.values.update(
            {
                "gear_position": gear_position,
                "flap_position": flap,
                "canopy_state": canopy,
                "master_arm": master_arm,
                "fuel_quantity": fuel,
                "master_caution": master_caution,
                "parking_brake": parking,
                "speed_brake": speed_brake,
                "refueling_probe": probe,
                "hook_position": hook,
                "ejection_seat_armed": seat,
                "weight_on_wheels": wow,
                "engine_rpm_left": rpm_left,
                "engine_rpm_right": rpm_right,
                "throttle_left": throttle_left,
                "throttle_right": throttle_right,
            }
        )
        result.warning_lights.update(warning_lights)
        result.raw.update(raw)
        return result

    def _gear_state(
        self,
        lever: TelemetryValue[Any],
        lights: list[TelemetryValue[Any]],
        *,
        now: float,
    ) -> GearState | None:
        if not lever.usable or not all(item.usable for item in lights):
            self._gear_up_candidate_since = None
            return None
        light_values = [bool(item.value) for item in lights]
        if all(light_values):
            self._gear_up_candidate_since = None
            return GearState.DOWN
        if lever.value == 0 and not any(light_values):
            if self._gear_up_candidate_since is None:
                self._gear_up_candidate_since = now
            if now - self._gear_up_candidate_since >= self.gear_up_dwell_seconds:
                return GearState.UP
            return GearState.TRANSIT
        self._gear_up_candidate_since = None
        return GearState.TRANSIT

    @staticmethod
    def _map_canopy(value: TelemetryValue[float]) -> TelemetryValue[CanopyState]:
        mapped: CanopyState | None = None
        if value.usable and value.value is not None:
            if value.value <= 0.02:
                mapped = CanopyState.CLOSED
            elif value.value >= 0.95:
                mapped = CanopyState.OPEN
            else:
                mapped = CanopyState.MOVING
        return TelemetryValue(
            value=mapped,
            available=value.available and mapped is not None,
            updated_at=value.updated_at,
            source=value.source,
            stale=value.stale,
        )

    @staticmethod
    def _map_bool(value: TelemetryValue[Any], predicate: Any) -> TelemetryValue[bool]:
        mapped = predicate(value.value) if value.usable else None
        return TelemetryValue(
            value=mapped,
            available=value.available and mapped is not None,
            updated_at=value.updated_at,
            source=value.source,
            stale=value.stale,
        )
