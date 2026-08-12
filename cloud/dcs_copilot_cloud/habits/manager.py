"""Aggregate allowlisted semantic rule outcomes without retaining raw telemetry."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
from uuid import uuid4

from ..rules.base import RuleTransition, RuleTransitionType
from ..rules.engine import RuleEngine
from ..state.models import AircraftState
from .models import HABIT_RULE_IDS, FlightSummary


class FlightStatsManager:
    """Tracks coverage and activations for one backend aircraft session."""

    def __init__(self, rule_engine: RuleEngine, *, pending_limit: int = 32) -> None:
        if pending_limit <= 0:
            raise ValueError("pending_limit must be greater than zero")
        engine_ids = {rule.id for rule in rule_engine.rules}
        if not engine_ids <= HABIT_RULE_IDS:
            raise ValueError("rule engine contains non-allowlisted habit rules")
        self.rule_engine = rule_engine
        self._aircraft: str | None = None
        self._covered: set[str] = set()
        self._activations: Counter[str] = Counter()
        self._pending: deque[FlightSummary] = deque(maxlen=pending_limit)
        self._callbacks: list[Callable[[FlightSummary], None]] = []
        rule_engine.add_transition_callback(self._on_transition)

    @property
    def pending(self) -> tuple[FlightSummary, ...]:
        return tuple(self._pending)

    def add_summary_callback(self, callback: Callable[[FlightSummary], None]) -> None:
        self._callbacks.append(callback)

    def observe(self, state: AircraftState) -> FlightSummary | None:
        aircraft = state.aircraft if state.connected else None
        completed = None
        if aircraft != self._aircraft:
            completed = self.finish()
            self._aircraft = aircraft
        if aircraft is not None:
            self._covered.update(self.rule_engine.evaluable_rule_ids(state))
        return completed

    def finish(self) -> FlightSummary | None:
        if self._aircraft is None:
            return None
        summary = FlightSummary(
            summary_id=str(uuid4()),
            aircraft=self._aircraft,
            rule_activations={
                rule_id: self._activations[rule_id]
                for rule_id in sorted(self._covered)
            },
        )
        self._aircraft = None
        self._covered.clear()
        self._activations.clear()
        self._pending.append(summary)
        for callback in tuple(self._callbacks):
            callback(summary)
        return summary

    def acknowledge(self, summary_id: str) -> bool:
        for summary in tuple(self._pending):
            if summary.summary_id == summary_id:
                self._pending.remove(summary)
                return True
        return False

    def _on_transition(self, transition: RuleTransition) -> None:
        if (
            self._aircraft is not None
            and transition.type is RuleTransitionType.ACTIVATED
            and transition.issue.rule_id in self._covered
        ):
            self._activations[transition.issue.rule_id] += 1
