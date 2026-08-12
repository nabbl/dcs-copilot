"""Tests for EventManager: proactive/non-proactive publishing, cooldown, reset."""

from __future__ import annotations

from dcs_copilot_cloud.events.manager import EventManager
from dcs_copilot_cloud.rules.base import (
    Rule,
    RuleContext,
    RuleResult,
    Severity,
)
from dcs_copilot_cloud.rules.engine import RuleEngine
from dcs_copilot_cloud.state.history import StateHistory
from dcs_copilot_cloud.state.models import AircraftState


class _ToggleRule(Rule):
    """Test-only rule whose activation is controlled by an external toggle."""

    id = "TEST_TOGGLE_RULE"
    severity = Severity.WARNING
    cooldown_seconds = 10.0
    required_fields = frozenset()

    def __init__(self, toggle: list[bool]) -> None:
        self._toggle = toggle

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if self._toggle[0]:
            return RuleResult(message="issue active", explanation="test rule active")
        return None


class _NonProactiveRule(Rule):
    """Test-only rule whose issues are explicitly marked non-proactive."""

    id = "TEST_NON_PROACTIVE_RULE"
    severity = Severity.WARNING
    cooldown_seconds = 0.0
    required_fields = frozenset()

    def __init__(self, toggle: list[bool]) -> None:
        self._toggle = toggle

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if self._toggle[0]:
            return RuleResult(
                message="issue active",
                explanation="test non-proactive rule",
                data={"proactive": False},
            )
        return None


def _connected_state() -> AircraftState:
    return AircraftState(aircraft="FA-18C_hornet", connected=True)


def test_proactive_transition_is_published() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleRule(toggle)])
    manager = EventManager(rule_engine)
    state = _connected_state()
    history = StateHistory()

    rule_engine.evaluate(state, history, now=0.0)

    assert len(manager.history) == 1
    managed = manager.history[0]
    assert managed.event.status == "RAISED"
    assert managed.publish is True
    assert managed.speak is True


def test_non_proactive_transition_is_not_published() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_NonProactiveRule(toggle)])
    manager = EventManager(rule_engine)
    state = _connected_state()
    history = StateHistory()

    rule_engine.evaluate(state, history, now=0.0)

    assert len(manager.history) == 1
    managed = manager.history[0]
    assert managed.publish is False
    assert managed.speak is False


def test_cooldown_suppresses_repeated_publish() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleRule(toggle)])
    manager = EventManager(rule_engine)
    state = _connected_state()
    history = StateHistory()

    # First activation at t=0: within cooldown window, should publish.
    rule_engine.evaluate(state, history, now=0.0)
    assert manager.history[-1].publish is True

    # Clear the condition, then re-trigger quickly (before cooldown elapses).
    toggle[0] = False
    rule_engine.evaluate(state, history, now=1.0)
    toggle[0] = True
    rule_engine.evaluate(state, history, now=2.0)

    reactivated = manager.history[-1]
    assert reactivated.event.status == "RAISED"
    # Still inside the 10s cooldown window from the first activation.
    assert reactivated.publish is False


def test_reset_clears_event_history() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleRule(toggle)])
    manager = EventManager(rule_engine)
    state = _connected_state()
    history = StateHistory()

    rule_engine.evaluate(state, history, now=0.0)
    assert len(manager.history) == 1

    manager.reset()
    assert manager.history == ()


def test_callback_receives_managed_events() -> None:
    toggle = [True]
    rule_engine = RuleEngine([_ToggleRule(toggle)])
    manager = EventManager(rule_engine)
    received = []
    manager.add_callback(received.append)
    state = _connected_state()
    history = StateHistory()

    rule_engine.evaluate(state, history, now=0.0)

    assert len(received) == 1
    assert received[0].event.rule_id == "TEST_TOGGLE_RULE"
