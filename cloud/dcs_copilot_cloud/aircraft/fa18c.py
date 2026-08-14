"""Verified F/A-18C Hornet normalization adapter (backend-authoritative)."""

from __future__ import annotations

from typing import Any

from ..state.models import (
    CanopyState,
    FlapState,
    GearState,
    MasterArmState,
    PartialAircraftState,
    TelemetryValue,
)
from .base import ControlReader, combine_values, map_value, parse_number
from .generic import GenericAircraftAdapter
from .raw import RawTelemetryKey, RawTelemetryStore

MODULE = "FA-18C_hornet"

# All FA-18C fraction controls use max_value=65535 in DCS-BIOS.
FA18C_FRACTION_CONTROLS = {
    "CANOPY_POS",
    "EXT_SPEED_BRAKE",
    "EXT_REFUEL_PROBE",
    "EXT_HOOK",
    "EXT_WING_FOLDING",
    "INT_THROTTLE_LEFT",
    "INT_THROTTLE_RIGHT",
    "HUD_SYM_BRT",
}

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
    def __init__(self) -> None:
        self.aircraft_names = {"FA-18C_hornet"}
        self.generic = GenericAircraftAdapter()
        self.gear_up_dwell_seconds = 3.0
        self._gear_up_candidate_since: float | None = None
        self._previous_wow: bool | None = None
        self._takeoff_trim_confirmed = False

    def _register_catalog(self, raw: RawTelemetryStore) -> None:
        for identifier in FA18C_FRACTION_CONTROLS:
            raw.catalog_register(
                RawTelemetryKey(MODULE, identifier, "integer", 0), max_value=65535
            )

    def normalize(
        self,
        raw: RawTelemetryStore,
        *,
        now: float,
    ) -> PartialAircraftState:
        self._register_catalog(raw)
        result = self.generic.normalize(raw, now=now)
        reader = ControlReader(raw, now=now)
        raw_values: dict[str, TelemetryValue[Any]] = {}

        def read_int(identifier: str) -> TelemetryValue[Any]:
            value = reader.read(MODULE, identifier, output_type="integer")
            raw_values[identifier] = value
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
            "derived:FA-18C_hornet/gear-composite",
        )

        wow_values = [
            read_int("EXT_WOW_NOSE"),
            read_int("EXT_WOW_LEFT"),
            read_int("EXT_WOW_RIGHT"),
        ]
        wow = combine_values(
            wow_values,
            any(bool(item.value) for item in wow_values)
            if all(item.available and item.value is not None for item in wow_values)
            else None,
            "derived:FA-18C_hornet/WOW-composite",
        )
        airborne = self._map_bool(wow, lambda value: not value)
        gear_commanded_down = self._map_bool(gear_lever, bool)

        flap = reader.read(
            MODULE,
            "FLAP_SW",
            map_value({0: FlapState.AUTO, 1: FlapState.HALF, 2: FlapState.FULL}),
            output_type="integer",
        )
        raw_values["FLAP_SW"] = flap

        canopy_fraction = reader.fraction(MODULE, "CANOPY_POS")
        raw_values["CANOPY_POS"] = canopy_fraction
        canopy = self._map_canopy(canopy_fraction)

        master_arm = reader.read(
            MODULE,
            "MASTER_ARM_SW",
            map_value({0: MasterArmState.SAFE, 1: MasterArmState.ARM}),
            output_type="integer",
        )
        raw_values["MASTER_ARM_SW"] = master_arm
        aa_mode_raw = read_int("MASTER_MODE_AA_LT")
        ag_mode_raw = read_int("MASTER_MODE_AG_LT")
        master_mode_combat = combine_values(
            [aa_mode_raw, ag_mode_raw],
            bool(aa_mode_raw.value) or bool(ag_mode_raw.value)
            if aa_mode_raw.available
            and aa_mode_raw.value is not None
            and ag_mode_raw.available
            and ag_mode_raw.value is not None
            else None,
            "derived:FA-18C_hornet/master-mode-composite",
        )

        fuel_upper = reader.read(
            MODULE, "IFEI_FUEL_UP", parse_number, output_type="string"
        )
        fuel_legend = reader.read(MODULE, "IFEI_T", output_type="string")
        raw_values["IFEI_FUEL_UP"] = fuel_upper
        raw_values["IFEI_T"] = fuel_legend
        fuel = combine_values(
            [fuel_upper, fuel_legend],
            float(fuel_upper.value)
            if fuel_upper.available
            and fuel_upper.value is not None
            and fuel_legend.available
            and fuel_legend.value is not None
            and str(fuel_legend.value).strip() == "T"
            else None,
            "derived:FA-18C_hornet/IFEI-total-fuel",
        )

        parking_raw = read_int("EMERGENCY_PARKING_BRAKE_ROTATE")
        parking_pull_raw = read_int("EMERGENCY_PARKING_BRAKE_PULL")
        parking = (
            self._map_bool(parking_pull_raw, bool)
            if parking_pull_raw.available
            else self._map_bool(parking_raw, lambda value: value != 2)
        )
        battery_raw = read_int("BATTERY_SW")
        # DCS exports OFF as the center position. Both end positions energize
        # the battery circuit (normal ON or guarded ORIDE).
        battery_on = self._map_bool(battery_raw, lambda value: value != 1)
        apu_ready_raw = read_int("APU_READY_LT")
        apu_ready = self._map_bool(apu_ready_raw, bool)
        read_int("L_GEN_SW")
        read_int("R_GEN_SW")
        bleed_air_raw = read_int("BLEED_AIR_KNOB")
        bleed_air_normal = self._map_bool(bleed_air_raw, lambda value: value != 3)
        ins_mode = reader.read(
            MODULE,
            "INS_SW",
            map_value(
                {
                    0: "OFF",
                    1: "CV",
                    2: "GND",
                    3: "NAV",
                    4: "IFA",
                    5: "GYRO",
                    6: "GB",
                    7: "TEST",
                }
            ),
            output_type="integer",
        )
        raw_values["INS_SW"] = ins_mode
        taxi_light_raw = read_int("LDG_TAXI_SW")
        taxi_light = self._map_bool(taxi_light_raw, bool)
        hud_brightness = reader.fraction(MODULE, "HUD_SYM_BRT")
        raw_values["HUD_SYM_BRT"] = hud_brightness

        speed_brake = reader.fraction(MODULE, "EXT_SPEED_BRAKE")
        raw_values["EXT_SPEED_BRAKE"] = speed_brake
        probe_raw = reader.fraction(MODULE, "EXT_REFUEL_PROBE")
        raw_values["EXT_REFUEL_PROBE"] = probe_raw
        probe = self._map_bool(probe_raw, lambda value: value > 0.1)
        hook_raw = reader.fraction(MODULE, "EXT_HOOK")
        raw_values["EXT_HOOK"] = hook_raw
        hook = self._map_bool(hook_raw, lambda value: value > 0.5)
        hook_command_raw = read_int("HOOK_LEVER")
        hook_commanded_down = self._map_bool(hook_command_raw, bool)

        seat_raw = read_int("EJECTION_SEAT_ARMED")
        # Live Hornet export: SAFE is 1 and ARMED is 0 for this handle.
        seat = self._map_bool(seat_raw, lambda value: value == 0)
        obogs_raw = read_int("OBOGS_SW")
        obogs = self._map_bool(obogs_raw, bool)
        launch_bar_raw = read_int("LAUNCH_BAR_SW")
        launch_bar = self._map_bool(launch_bar_raw, bool)
        wing_fold_raw = reader.fraction(MODULE, "EXT_WING_FOLDING")
        raw_values["EXT_WING_FOLDING"] = wing_fold_raw
        wing_fold_spread = self._map_bool(wing_fold_raw, lambda value: value <= 0.05)
        takeoff_trim_raw = read_int("TO_TRIM_BTN")
        takeoff_trim_pressed = self._map_bool(takeoff_trim_raw, bool)
        takeoff_trim_confirmed = self._update_takeoff_trim_confirmed(
            takeoff_trim_pressed,
            wow,
        )

        rpm_left = reader.read(MODULE, "IFEI_RPM_L", parse_number, output_type="string")
        rpm_right = reader.read(
            MODULE, "IFEI_RPM_R", parse_number, output_type="string"
        )
        raw_values["IFEI_RPM_L"] = rpm_left
        raw_values["IFEI_RPM_R"] = rpm_right
        throttle_left = reader.fraction(MODULE, "INT_THROTTLE_LEFT")
        throttle_right = reader.fraction(MODULE, "INT_THROTTLE_RIGHT")
        raw_values["INT_THROTTLE_LEFT"] = throttle_left
        raw_values["INT_THROTTLE_RIGHT"] = throttle_right

        master_caution_raw = read_int("MASTER_CAUTION_LT")
        master_caution = self._map_bool(master_caution_raw, bool)
        warning_lights: dict[str, TelemetryValue[bool]] = {}
        for semantic_name, identifier in WARNING_LIGHTS.items():
            warning_lights[semantic_name] = self._map_bool(read_int(identifier), bool)
        left_generator_normal = self._generator_online(
            rpm_left, warning_lights["left_generator"]
        )
        right_generator_normal = self._generator_online(
            rpm_right, warning_lights["right_generator"]
        )
        ias = result.values.get("indicated_airspeed")
        carrier_launch_sequence = combine_values(
            [wow, launch_bar],
            bool(wow.value) and bool(launch_bar.value)
            if wow.available
            and wow.value is not None
            and launch_bar.available
            and launch_bar.value is not None
            else None,
            "derived:FA-18C_hornet/carrier-launch-derived",
        )
        takeoff_sequence = combine_values(
            [wow, launch_bar, ias] if ias is not None else [wow, launch_bar],
            (
                bool(carrier_launch_sequence.value)
                or (
                    bool(wow.value)
                    and ias is not None
                    and ias.value is not None
                    and float(ias.value) >= 80
                )
            )
            if wow.available
            and wow.value is not None
            and launch_bar.available
            and launch_bar.value is not None
            and ias is not None
            and ias.available
            and ias.value is not None
            else None,
            "derived:FA-18C_hornet/takeoff-sequence-derived",
        )

        result.values.update(
            {
                "gear_position": gear_position,
                "flap_position": flap,
                "canopy_state": canopy,
                "master_arm": master_arm,
                "fuel_quantity": fuel,
                "master_caution": master_caution,
                "parking_brake": parking,
                "battery_on": battery_on,
                "apu_ready": apu_ready,
                "left_generator_normal": left_generator_normal,
                "right_generator_normal": right_generator_normal,
                "bleed_air_normal": bleed_air_normal,
                "ins_mode": ins_mode,
                "taxi_light_on": taxi_light,
                "hud_brightness": hud_brightness,
                "speed_brake": speed_brake,
                "refueling_probe": probe,
                "hook_position": hook,
                "hook_commanded_down": hook_commanded_down,
                "ejection_seat_armed": seat,
                "obogs_on": obogs,
                "weight_on_wheels": wow,
                "engine_rpm_left": rpm_left,
                "engine_rpm_right": rpm_right,
                "throttle_left": throttle_left,
                "throttle_right": throttle_right,
                "gear_commanded_down": gear_commanded_down,
                "launch_bar_deployed": launch_bar,
                "wing_fold_spread": wing_fold_spread,
                "takeoff_trim_pressed": takeoff_trim_pressed,
                "takeoff_trim_confirmed": takeoff_trim_confirmed,
                "master_mode_combat": master_mode_combat,
                "airborne": airborne,
                "takeoff_sequence": takeoff_sequence,
                "carrier_launch_sequence": carrier_launch_sequence,
            }
        )
        result.warning_lights.update(warning_lights)
        result.raw.update(raw_values)
        return result

    @staticmethod
    def _generator_online(
        rpm: TelemetryValue[Any], caution: TelemetryValue[bool]
    ) -> TelemetryValue[bool]:
        online = (
            float(rpm.value) > 60 and not bool(caution.value)
            if rpm.available and rpm.value is not None and caution.available
            else None
        )
        return combine_values(
            [rpm, caution],
            online,
            "derived:FA-18C_hornet/generator-online",
        )

    def _update_takeoff_trim_confirmed(
        self,
        takeoff_trim_pressed: TelemetryValue[bool],
        wow: TelemetryValue[bool],
    ) -> TelemetryValue[bool]:
        if wow.usable:
            current_wow = bool(wow.value)
            if self._previous_wow is False and current_wow:
                self._takeoff_trim_confirmed = False
            self._previous_wow = current_wow
        else:
            self._previous_wow = None
        if takeoff_trim_pressed.usable and takeoff_trim_pressed.value:
            self._takeoff_trim_confirmed = True
        return TelemetryValue(
            value=self._takeoff_trim_confirmed
            if takeoff_trim_pressed.available
            else None,
            available=takeoff_trim_pressed.available,
            updated_at=takeoff_trim_pressed.updated_at,
            source="derived:FA-18C_hornet/takeoff-trim-confirmed",
            stale=takeoff_trim_pressed.stale,
        )

    def _gear_state(
        self,
        lever: TelemetryValue[Any],
        lights: list[TelemetryValue[Any]],
        *,
        now: float,
    ) -> GearState | None:
        if (
            not lever.available
            or lever.value is None
            or not all(item.available and item.value is not None for item in lights)
        ):
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
        if value.available and value.value is not None:
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
        mapped = (
            predicate(value.value)
            if value.available and value.value is not None
            else None
        )
        return TelemetryValue(
            value=mapped,
            available=value.available and mapped is not None,
            updated_at=value.updated_at,
            source=value.source,
            stale=value.stale,
        )
