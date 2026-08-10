from __future__ import annotations

from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState, TelemetryValue


def state_at_altitude(value: float | None) -> AircraftState:
    telemetry = (
        TelemetryValue(value, True, 0, "test")
        if value is not None
        else TelemetryValue.unavailable("test")
    )
    return AircraftState(connected=True, altitude_msl=telemetry)


def test_history_compacts_small_numeric_changes_and_calculates_rate() -> None:
    history = StateHistory(retention_seconds=60)
    history.record(state_at_altitude(1000), timestamp=0)
    history.record(state_at_altitude(1005), timestamp=1)
    history.record(state_at_altitude(1020), timestamp=2)
    transitions = history.transitions("altitude_msl")
    assert [(item.old_value, item.new_value) for item in transitions] == [
        (None, 1000),
        (1000, 1020),
    ]
    assert history.rate("altitude_msl", seconds=10, now=2) == 10


def test_history_tracks_availability_loss_and_prunes() -> None:
    history = StateHistory(retention_seconds=5)
    history.record(state_at_altitude(1000), timestamp=0)
    history.record(state_at_altitude(None), timestamp=1)
    assert history.transitions("altitude_msl")[-1].new_value is None
    history.prune(10)
    assert history.transitions() == ()
