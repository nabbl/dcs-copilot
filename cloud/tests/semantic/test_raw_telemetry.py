"""Tests for RawTelemetryStore bounded eviction, staleness, and catalog behavior."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey, RawTelemetryStore
from dcs_copilot_cloud.state.models import TelemetryStatus


def test_read_unavailable_when_never_updated() -> None:
    store = RawTelemetryStore()
    key = RawTelemetryKey("FA-18C_hornet", "BATTERY_SW", "integer", 0)
    result = store.read(key, now=0.0)
    assert result.status is TelemetryStatus.UNAVAILABLE
    assert not result.available


def test_update_then_read_available() -> None:
    store = RawTelemetryStore()
    key = RawTelemetryKey("FA-18C_hornet", "BATTERY_SW", "integer", 0)
    store.update(key, 0, received_at=10.0)
    result = store.read(key, now=10.0)
    assert result.available
    assert result.value == 0
    assert result.status is TelemetryStatus.AVAILABLE


def test_read_stale_after_timeout() -> None:
    store = RawTelemetryStore(stale_timeout=5.0)
    key = RawTelemetryKey("FA-18C_hornet", "BATTERY_SW", "integer", 0)
    store.update(key, 1, received_at=0.0)
    fresh = store.read(key, now=4.0)
    assert fresh.status is TelemetryStatus.AVAILABLE
    stale = store.read(key, now=6.0)
    assert stale.status is TelemetryStatus.STALE
    assert stale.available
    assert stale.stale


def test_bounded_eviction_evicts_oldest() -> None:
    store = RawTelemetryStore(max_controls=2)
    key_a = RawTelemetryKey("FA-18C_hornet", "A", "integer", 0)
    key_b = RawTelemetryKey("FA-18C_hornet", "B", "integer", 0)
    key_c = RawTelemetryKey("FA-18C_hornet", "C", "integer", 0)
    store.update(key_a, 1, received_at=0.0)
    store.update(key_b, 2, received_at=1.0)
    assert store.entry_count == 2
    store.update(key_c, 3, received_at=2.0)
    assert store.entry_count == 2
    assert not store.read(key_a, now=2.0).available
    assert store.read(key_b, now=2.0).available
    assert store.read(key_c, now=2.0).available


def test_updating_existing_key_does_not_evict() -> None:
    store = RawTelemetryStore(max_controls=2)
    key_a = RawTelemetryKey("FA-18C_hornet", "A", "integer", 0)
    key_b = RawTelemetryKey("FA-18C_hornet", "B", "integer", 0)
    store.update(key_a, 1, received_at=0.0)
    store.update(key_b, 2, received_at=1.0)
    store.update(key_a, 5, received_at=2.0)
    assert store.entry_count == 2
    assert store.read(key_a, now=2.0).value == 5
    assert store.read(key_b, now=2.0).available


def test_catalog_register_and_max_value() -> None:
    store = RawTelemetryStore()
    key = RawTelemetryKey("FA-18C_hornet", "CANOPY_POS", "integer", 0)
    assert not store.is_cataloged(key)
    assert store.catalog_max_value(key) is None
    store.catalog_register(key, max_value=65535)
    assert store.is_cataloged(key)
    assert store.catalog_max_value(key) == 65535


def test_catalog_register_is_idempotent() -> None:
    store = RawTelemetryStore()
    key = RawTelemetryKey("FA-18C_hornet", "CANOPY_POS", "integer", 0)
    store.catalog_register(key, max_value=65535)
    store.catalog_register(key, max_value=65535)
    assert store.catalog_max_value(key) == 65535


def test_clear_removes_entries_but_keeps_catalog() -> None:
    store = RawTelemetryStore()
    key = RawTelemetryKey("FA-18C_hornet", "BATTERY_SW", "integer", 0)
    store.catalog_register(key, max_value=1)
    store.update(key, 1, received_at=0.0)
    assert store.entry_count == 1
    store.clear()
    assert store.entry_count == 0
    assert not store.read(key, now=0.0).available
    # catalog registration is preserved across clear()
    assert store.is_cataloged(key)
