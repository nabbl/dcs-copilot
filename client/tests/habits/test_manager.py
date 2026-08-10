from __future__ import annotations

from dcs_copilot.habits import FlightStatsManager
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import MasterCautionRule
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState, FlightPhase, TelemetryValue


def state(caution: bool | None, *, connected: bool = True) -> AircraftState:
    return AircraftState(
        aircraft="FA-18C_hornet",
        connected=connected,
        flight_phase=FlightPhase.CRUISE,
        master_caution=TelemetryValue(
            caution,
            available=caution is not None,
            updated_at=0 if caution is not None else None,
        ),
    )


def test_flight_statistics_count_deterministic_activations_and_acknowledge() -> None:
    engine = RuleEngine([MasterCautionRule()])
    manager = FlightStatsManager(engine)
    history = StateHistory()
    caution = state(True)
    manager.observe(caution)
    engine.evaluate(caution, history, now=0)
    engine.evaluate(caution, history, now=0.25)

    clear = state(False)
    manager.observe(clear)
    engine.evaluate(clear, history, now=1)
    engine.evaluate(clear, history, now=1.5)
    summary = manager.finish()

    assert summary is not None
    assert summary.rule_activations == {"FA18_MASTER_CAUTION": 1}
    assert manager.pending == (summary,)
    assert manager.acknowledge(summary.summary_id)
    assert manager.pending == ()


def test_unavailable_telemetry_is_omitted_instead_of_guessed_clear() -> None:
    engine = RuleEngine([MasterCautionRule()])
    manager = FlightStatsManager(engine)
    unavailable = state(None)

    manager.observe(unavailable)
    engine.evaluate(unavailable, StateHistory(), now=0)
    summary = manager.finish()

    assert summary is not None
    assert summary.rule_activations == {}


def test_disconnect_finishes_flight_and_callback_retains_pending_summary() -> None:
    engine = RuleEngine([MasterCautionRule()])
    manager = FlightStatsManager(engine)
    delivered = []
    manager.add_summary_callback(delivered.append)
    manager.observe(state(False))

    completed = manager.observe(state(None, connected=False))

    assert completed is not None
    assert delivered == [completed]
    assert manager.pending == (completed,)
