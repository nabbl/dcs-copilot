"""Normalization tests for Hornet gear and arresting-hook positions."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.fa18c import FA18CAdapter
from dcs_copilot_cloud.aircraft.raw import RawTelemetryStore
from dcs_copilot_cloud.state.models import GearState

from .helpers import set_int


def _set_gear(
    raw: RawTelemetryStore,
    *,
    lever: int,
    lights: tuple[int, int, int],
    now: float,
) -> None:
    set_int(raw, "GEAR_LEVER", lever, now=now)
    set_int(raw, "FLP_LG_NOSE_GEAR_LT", lights[0], now=now)
    set_int(raw, "FLP_LG_LEFT_GEAR_LT", lights[1], now=now)
    set_int(raw, "FLP_LG_RIGHT_GEAR_LT", lights[2], now=now)


def test_gear_handle_down_and_three_green_lights_report_gear_down() -> None:
    raw = RawTelemetryStore()
    _set_gear(raw, lever=0, lights=(1, 1, 1), now=100.0)

    result = FA18CAdapter().normalize(raw, now=100.0)

    assert result.values["gear_commanded_down"].value is True
    assert result.values["gear_position"].value is GearState.DOWN


def test_gear_handle_up_and_dark_lights_report_gear_up_after_dwell() -> None:
    raw = RawTelemetryStore()
    adapter = FA18CAdapter()
    _set_gear(raw, lever=1, lights=(0, 0, 0), now=100.0)

    moving = adapter.normalize(raw, now=100.0)
    retracted = adapter.normalize(raw, now=104.0)

    assert moving.values["gear_commanded_down"].value is False
    assert moving.values["gear_position"].value is GearState.TRANSIT
    assert retracted.values["gear_position"].value is GearState.UP


def test_hook_handle_and_external_position_use_their_export_directions() -> None:
    hook_up_raw = RawTelemetryStore()
    set_int(hook_up_raw, "HOOK_LEVER", 1, now=100.0)
    set_int(hook_up_raw, "EXT_HOOK", 0, now=100.0)

    hook_down_raw = RawTelemetryStore()
    set_int(hook_down_raw, "HOOK_LEVER", 0, now=100.0)
    set_int(hook_down_raw, "EXT_HOOK", 65535, now=100.0)

    hook_up = FA18CAdapter().normalize(hook_up_raw, now=100.0)
    hook_down = FA18CAdapter().normalize(hook_down_raw, now=100.0)

    assert hook_up.values["hook_commanded_down"].value is False
    assert hook_up.values["hook_position"].value is False
    assert hook_down.values["hook_commanded_down"].value is True
    assert hook_down.values["hook_position"].value is True
