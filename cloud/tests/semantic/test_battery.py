"""Tests for FA-18C battery-switch normalization semantics."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.fa18c import FA18CAdapter
from dcs_copilot_cloud.aircraft.raw import RawTelemetryStore
from dcs_copilot_cloud.state.models import TelemetryStatus

from .helpers import set_int


def test_battery_on_when_switch_is_normal_on_position() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "BATTERY_SW", 0, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    battery_on = result.values["battery_on"]
    assert battery_on.usable
    assert battery_on.value is True


def test_battery_off_when_switch_is_one() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "BATTERY_SW", 1, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    battery_on = result.values["battery_on"]
    assert battery_on.usable
    assert battery_on.value is False


def test_battery_on_when_switch_is_override_position() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "BATTERY_SW", 2, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    battery_on = result.values["battery_on"]
    assert battery_on.usable
    assert battery_on.value is True


def test_stale_battery_switch_is_not_usable() -> None:
    raw = RawTelemetryStore(stale_timeout=5.0)
    set_int(raw, "BATTERY_SW", 0, now=0.0)
    adapter = FA18CAdapter()
    # Normalize far enough in the future that the raw value is stale.
    result = adapter.normalize(raw, now=100.0)
    battery_on = result.values["battery_on"]
    # A stale/unconfirmed reading must never be reported as a usable boolean.
    assert not battery_on.usable
    assert battery_on.status == TelemetryStatus.STALE
