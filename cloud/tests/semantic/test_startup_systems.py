"""Normalization tests for Hornet startup electrical and bleed-air state."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.fa18c import FA18CAdapter
from dcs_copilot_cloud.aircraft.raw import RawTelemetryStore

from .helpers import set_int, set_str


def test_generators_are_online_when_engines_run_without_generator_cautions() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_str(raw, "IFEI_RPM_L", "70", now=now)
    set_str(raw, "IFEI_RPM_R", "70", now=now)
    set_int(raw, "CLIP_L_GEN_LT", 0, now=now)
    set_int(raw, "CLIP_R_GEN_LT", 0, now=now)

    result = FA18CAdapter().normalize(raw, now=now)

    assert result.values["left_generator_normal"].value is True
    assert result.values["right_generator_normal"].value is True


def test_generator_caution_reports_that_generator_offline() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_str(raw, "IFEI_RPM_L", "70", now=now)
    set_int(raw, "CLIP_L_GEN_LT", 1, now=now)

    result = FA18CAdapter().normalize(raw, now=now)

    assert result.values["left_generator_normal"].value is False


def test_bleed_air_supply_is_active_in_each_non_off_position() -> None:
    for position in (0, 1, 2):
        raw = RawTelemetryStore()
        set_int(raw, "BLEED_AIR_KNOB", position, now=100.0)

        result = FA18CAdapter().normalize(raw, now=100.0)

        assert result.values["bleed_air_normal"].value is True


def test_bleed_air_supply_is_inactive_in_explicit_off_position() -> None:
    raw = RawTelemetryStore()
    set_int(raw, "BLEED_AIR_KNOB", 3, now=100.0)

    result = FA18CAdapter().normalize(raw, now=100.0)

    assert result.values["bleed_air_normal"].value is False
