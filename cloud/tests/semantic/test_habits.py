"""Tests for FlightStatsManager and the cloud-local FlightSummary/HABIT_RULE_IDS."""

from __future__ import annotations

import pytest

from dcs_copilot_cloud.habits.manager import FlightStatsManager
from dcs_copilot_cloud.habits.models import HABIT_RULE_IDS, MAX_SUMMARY_RULES, FlightSummary
from dcs_copilot_cloud.rules.base import Rule, RuleContext, RuleResult, Severity
from dcs_copilot_cloud.rules.engine import RuleEngine
from dcs_copilot_cloud.state.history import StateHistory
from dcs_copilot_cloud.state.models import AircraftState


class _ToggleHabitRule(Rule):
    id = "FA18_MASTER_CAUTION"
    severity = Severity.WARNING
    cooldown_seconds = 0.0
    required_fields = frozenset()

    def __init__(self, toggle: list[bool]) -> None:
        self._toggle = toggle

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if self._toggle[0]:
            return RuleResult(message="caution", explanation="test")
        return None


def test_flight_summary_generated_at_end_of_flight() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleHabitRule(toggle)])
    manager = FlightStatsManager(rule_engine)
    history = StateHistory()

    state = AircraftState(aircraft="FA-18C_hornet", connected=True)
    manager.observe(state)
    rule_engine.evaluate(state, history, now=0.0)

    summary = manager.finish()
    assert summary is not None
    assert summary.aircraft == "FA-18C_hornet"
    assert summary.rule_activations.get("FA18_MASTER_CAUTION") == 1


def test_observe_aircraft_change_finishes_prior_flight() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleHabitRule(toggle)])
    manager = FlightStatsManager(rule_engine)
    history = StateHistory()

    state_a = AircraftState(aircraft="FA-18C_hornet", connected=True)
    manager.observe(state_a)
    rule_engine.evaluate(state_a, history, now=0.0)

    state_b = AircraftState(aircraft="A-10C_2", connected=True)
    completed = manager.observe(state_b)

    assert completed is not None
    assert completed.aircraft == "FA-18C_hornet"


def test_rule_engine_with_non_allowlisted_rule_rejected() -> None:
    class _NotHabitRule(Rule):
        id = "NOT_A_HABIT_RULE"
        severity = Severity.INFO
        cooldown_seconds = 0.0
        required_fields = frozenset()

        def evaluate(self, context: RuleContext) -> RuleResult | None:
            return None

    rule_engine = RuleEngine([_NotHabitRule()])
    with pytest.raises(ValueError, match="non-allowlisted"):
        FlightStatsManager(rule_engine)


def test_flight_summary_rejects_unknown_rule_id() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        FlightSummary(
            summary_id="8f14e45f-ceea-467e-bd3e-1c50f7a0e0f0",
            aircraft="FA-18C_hornet",
            rule_activations={"NOT_A_REAL_RULE": 1},
        )


def test_flight_summary_bounded_by_max_summary_rules() -> None:
    # The real allowlist has fewer entries than MAX_SUMMARY_RULES, so exceed the
    # count bound with synthetic ids; the count check runs before the allowlist
    # check, so this exercises the MAX_SUMMARY_RULES limit specifically.
    activations = {f"RULE_{i}": 0 for i in range(MAX_SUMMARY_RULES + 1)}
    with pytest.raises(ValueError, match=f"at most {MAX_SUMMARY_RULES}"):
        FlightSummary(
            summary_id="8f14e45f-ceea-467e-bd3e-1c50f7a0e0f0",
            aircraft="FA-18C_hornet",
            rule_activations=activations,
        )


def test_flight_summary_accepts_all_allowlisted_rules() -> None:
    assert len(HABIT_RULE_IDS) <= MAX_SUMMARY_RULES
    activations = {rule_id: 0 for rule_id in HABIT_RULE_IDS}
    summary = FlightSummary(
        summary_id="8f14e45f-ceea-467e-bd3e-1c50f7a0e0f0",
        aircraft="FA-18C_hornet",
        rule_activations=activations,
    )
    assert len(summary.rule_activations) == len(HABIT_RULE_IDS)
