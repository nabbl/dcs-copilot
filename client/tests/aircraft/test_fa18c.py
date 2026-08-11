from __future__ import annotations

import pytest
from conftest import set_control
from dcs_copilot.aircraft.fa18c import WARNING_LIGHTS, FA18CAdapter
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import (
    CanopyState,
    FlapState,
    GearState,
    MasterArmState,
)


def populate_hornet(
    registry: DcsBiosControlRegistry,
    state: DcsBiosState,
    *,
    timestamp: float = 100,
) -> None:
    for identifier, value in {
        "IAS_US_INT": 145,
        "ALT_MSL_FT": 5000,
        "HDG_DEG_MAG": 90,
        "TIME_MODEL_HIGH": 0,
        "TIME_MODEL_LOW": 100,
    }.items():
        set_control(
            registry, state, "CommonData", identifier, value, timestamp=timestamp
        )
    values: dict[str, int | str] = {
        "GEAR_LEVER": 1,
        "FLP_LG_NOSE_GEAR_LT": 1,
        "FLP_LG_LEFT_GEAR_LT": 1,
        "FLP_LG_RIGHT_GEAR_LT": 1,
        "EXT_WOW_NOSE": 1,
        "EXT_WOW_LEFT": 1,
        "EXT_WOW_RIGHT": 1,
        "FLAP_SW": 1,
        "CANOPY_POS": 0,
        "MASTER_ARM_SW": 1,
        "IFEI_FUEL_UP": "12500",
        "IFEI_T": "T",
        "EMERGENCY_PARKING_BRAKE_ROTATE": 1,
        "EXT_SPEED_BRAKE": 32768,
        "EXT_REFUEL_PROBE": 0,
        "EXT_HOOK": 65535,
        "HOOK_LEVER": 1,
        "LDG_TAXI_SW": 1,
        "EJECTION_SEAT_ARMED": 1,
        "OBOGS_SW": 1,
        "LAUNCH_BAR_SW": 0,
        "TO_TRIM_BTN": 0,
        "MASTER_MODE_AA_LT": 0,
        "MASTER_MODE_AG_LT": 0,
        "EXT_WING_FOLDING": 0,
        "IFEI_RPM_L": " 70",
        "IFEI_RPM_R": " 71",
        "INT_THROTTLE_LEFT": 32768,
        "INT_THROTTLE_RIGHT": 65535,
        "MASTER_CAUTION_LT": 1,
        **{identifier: 0 for identifier in WARNING_LIGHTS.values()},
    }
    values["CLIP_FUEL_LO_LT"] = 1
    for identifier, value in values.items():
        set_control(
            registry, state, "FA-18C_hornet", identifier, value, timestamp=timestamp
        )


def test_normalizes_verified_hornet_controls(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    populate_hornet(normalization_registry, state)

    result = FA18CAdapter(normalization_registry).normalize(
        state, now=101, stale_timeout=30
    )

    assert result.values["gear_position"].value is GearState.DOWN
    assert result.values["weight_on_wheels"].value is True
    assert result.values["flap_position"].value is FlapState.HALF
    assert result.values["canopy_state"].value is CanopyState.CLOSED
    assert result.values["master_arm"].value is MasterArmState.ARM
    assert result.values["fuel_quantity"].value == 12500
    assert result.values["parking_brake"].value is True
    assert result.values["taxi_light_on"].value is True
    assert result.values["speed_brake"].value == pytest.approx(0.5, abs=0.001)
    assert result.values["refueling_probe"].value is False
    assert result.values["hook_position"].value is True
    assert result.values["hook_commanded_down"].value is True
    assert result.values["ejection_seat_armed"].value is True
    assert result.values["obogs_on"].value is True
    assert result.values["engine_rpm_left"].value == 70
    assert result.values["throttle_right"].value == 1.0
    assert result.values["launch_bar_deployed"].value is False
    assert result.values["wing_fold_spread"].value is True
    assert result.values["takeoff_trim_confirmed"].value is False
    assert result.values["master_mode_combat"].value is False
    assert result.values["master_caution"].value is True
    assert result.warning_lights["fuel_low"].value is True


def test_fuel_is_unavailable_when_ifei_is_showing_another_tank_pair(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    populate_hornet(normalization_registry, state)
    set_control(
        normalization_registry,
        state,
        "FA-18C_hornet",
        "IFEI_T",
        "FL",
        timestamp=101,
    )
    result = FA18CAdapter(normalization_registry).normalize(
        state, now=102, stale_timeout=30
    )
    assert not result.values["fuel_quantity"].available


def test_gear_uses_lights_and_lever_and_reports_transit(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    populate_hornet(normalization_registry, state)
    set_control(
        normalization_registry,
        state,
        "FA-18C_hornet",
        "FLP_LG_NOSE_GEAR_LT",
        0,
        timestamp=101,
    )
    result = FA18CAdapter(normalization_registry).normalize(
        state, now=102, stale_timeout=30
    )
    assert result.values["gear_position"].value is GearState.TRANSIT


def test_missing_required_composite_input_disables_field(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    set_control(
        normalization_registry,
        state,
        "FA-18C_hornet",
        "GEAR_LEVER",
        1,
        timestamp=1,
    )
    result = FA18CAdapter(normalization_registry).normalize(
        state, now=2, stale_timeout=30
    )
    assert not result.values["gear_position"].available
    assert not result.values["weight_on_wheels"].available


def test_gear_up_requires_stable_lever_and_dark_lights(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    populate_hornet(normalization_registry, state)
    for identifier in (
        "GEAR_LEVER",
        "FLP_LG_NOSE_GEAR_LT",
        "FLP_LG_LEFT_GEAR_LT",
        "FLP_LG_RIGHT_GEAR_LT",
    ):
        set_control(
            normalization_registry,
            state,
            "FA-18C_hornet",
            identifier,
            0,
            timestamp=100,
        )
    adapter = FA18CAdapter(normalization_registry)
    first = adapter.normalize(state, now=101, stale_timeout=30)
    stable = adapter.normalize(state, now=105, stale_timeout=30)
    assert first.values["gear_position"].value is GearState.TRANSIT
    assert stable.values["gear_position"].value is GearState.UP
