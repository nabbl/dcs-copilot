"""Tests for AircraftStateStore epoch reset on aircraft change and disconnection."""

from __future__ import annotations

from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey
from dcs_copilot_cloud.state.store import AircraftStateStore

from .helpers import minimal_wow_grounded, set_int


def _prime_store(store: AircraftStateStore, *, now: float) -> None:
    minimal_wow_grounded(store.raw, now=now)
    set_int(store.raw, "BATTERY_SW", 0, now=now)
    store.update(aircraft="FA-18C_hornet", connected=True, now=now)
    store.checklist_engine.start("fa18c_startup", "pre-start")


def test_history_reset_on_aircraft_change() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    assert store.history.latest_value("battery_on") is True

    # Switching to a different aircraft must reset accumulated history so the
    # old aircraft's transitions cannot leak into the new epoch.
    store.update(aircraft="A-10C_2", connected=True, now=1.0)
    assert store.history.latest_value("battery_on") is None


def test_checklist_session_stopped_on_aircraft_change() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    assert store.checklist_engine.session.checklist_id == "fa18c_startup"

    store.update(aircraft="A-10C_2", connected=True, now=1.0)
    assert store.checklist_engine.session.checklist_id is None
    assert store.checklist_engine.session.stage_id is None


def test_rule_engine_active_issues_cleared_on_aircraft_change() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    store.update(aircraft="A-10C_2", connected=True, now=1.0)
    assert store.rule_engine.active_issues == ()


def test_event_history_cleared_on_aircraft_change() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    store.update(aircraft="A-10C_2", connected=True, now=1.0)
    assert store.event_manager.history == ()


def test_reset_also_happens_on_disconnection() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    assert store.checklist_engine.session.checklist_id == "fa18c_startup"

    store.update(aircraft="FA-18C_hornet", connected=False, now=1.0)

    assert store.history.latest_value("battery_on") is None
    assert store.checklist_engine.session.checklist_id is None
    assert store.rule_engine.active_issues == ()
    assert store.event_manager.history == ()
    assert store.current.connected is False


def test_flight_stats_finishes_prior_flight_on_aircraft_change() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)

    received = []
    store.flight_stats.add_summary_callback(received.append)
    store.update(aircraft="A-10C_2", connected=True, now=1.0)

    assert len(received) == 1
    assert received[0].aircraft == "FA-18C_hornet"


def test_flight_stats_finishes_prior_flight_on_disconnection() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)

    received = []
    store.flight_stats.add_summary_callback(received.append)
    store.update(aircraft="FA-18C_hornet", connected=False, now=1.0)

    assert len(received) == 1
    assert received[0].aircraft == "FA-18C_hornet"


def test_new_epoch_starts_clean_after_reset() -> None:
    store = AircraftStateStore()
    _prime_store(store, now=0.0)
    store.update(aircraft="A-10C_2", connected=True, now=1.0)

    # New aircraft has no telemetry set up yet; the store should reflect a
    # freshly-normalized (mostly-unavailable) state, not stale FA-18C values.
    state = store.current
    assert state.aircraft == "A-10C_2"
    assert state.connected is True
