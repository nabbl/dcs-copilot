"""Tests for FA-18C parking-brake pull/rotate fallback normalization."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.fa18c import FA18CAdapter
from dcs_copilot_cloud.aircraft.raw import RawTelemetryStore

from .helpers import set_int


def test_parking_pull_authoritative_when_available() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "EMERGENCY_PARKING_BRAKE_PULL", 1, now=now)
    # Rotate says NOT parked (2 == not parked), but pull should win.
    set_int(raw, "EMERGENCY_PARKING_BRAKE_ROTATE", 2, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    parking = result.values["parking_brake"]
    assert parking.usable
    assert parking.value is True


def test_parking_pull_false_when_available() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "EMERGENCY_PARKING_BRAKE_PULL", 0, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    parking = result.values["parking_brake"]
    assert parking.usable
    assert parking.value is False


def test_falls_back_to_rotate_when_pull_unavailable() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    # rotate == 2 means "not parked" per the client-verified mapping.
    set_int(raw, "EMERGENCY_PARKING_BRAKE_ROTATE", 2, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    parking = result.values["parking_brake"]
    assert parking.usable
    assert parking.value is False


def test_rotate_fallback_parked_when_not_two() -> None:
    raw = RawTelemetryStore()
    now = 100.0
    set_int(raw, "EMERGENCY_PARKING_BRAKE_ROTATE", 0, now=now)
    adapter = FA18CAdapter()
    result = adapter.normalize(raw, now=now)
    parking = result.values["parking_brake"]
    assert parking.usable
    assert parking.value is True
