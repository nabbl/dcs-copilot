"""Deterministic rule lifecycle, debounce, resolution, and cooldown handling."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState

from .base import (
    ActiveIssue,
    Rule,
    RuleContext,
    RuleResult,
    RuleTransition,
    RuleTransitionType,
    Severity,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _RuleRuntime:
    issue: ActiveIssue | None = None
    candidate_active: bool | None = None
    candidate_since: float | None = None
    candidate_result: RuleResult | None = None
    last_notification_at: float | None = None


@dataclass(frozen=True, slots=True)
class RuleDiagnostic:
    rule_id: str
    status: str
    reason: str
    metadata: dict[str, str]


class RuleEngine:
    def __init__(self, rules: Iterable[Rule]) -> None:
        rule_list = tuple(rules)
        ids = [rule.id for rule in rule_list]
        if len(ids) != len(set(ids)):
            raise ValueError("rule identifiers must be unique")
        self.rules = rule_list
        self._runtime = {rule.id: _RuleRuntime() for rule in rule_list}
        self._callbacks: list[Callable[[RuleTransition], None]] = []

    @property
    def active_issues(self) -> tuple[ActiveIssue, ...]:
        issues = [runtime.issue for runtime in self._runtime.values()]
        return tuple(
            sorted(
                (issue for issue in issues if issue is not None),
                key=lambda item: (-_severity_rank(item.severity), item.activated_at),
            )
        )

    def add_transition_callback(
        self, callback: Callable[[RuleTransition], None]
    ) -> None:
        self._callbacks.append(callback)

    def evaluable_rule_ids(self, state: AircraftState) -> frozenset[str]:
        """Return rules whose allowlisted local inputs are usable right now."""

        return frozenset(rule.id for rule in self.rules if self._applicable(rule, state))

    def diagnostics(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> tuple[RuleDiagnostic, ...]:
        diagnostics: list[RuleDiagnostic] = []
        telemetry = state.telemetry()
        for rule in self.rules:
            runtime = self._runtime[rule.id]
            if not state.connected:
                diagnostics.append(
                    RuleDiagnostic(rule.id, "disabled", "not connected", rule.metadata())
                )
                continue
            if rule.aircraft_names is not None and state.aircraft not in rule.aircraft_names:
                diagnostics.append(
                    RuleDiagnostic(rule.id, "disabled", "wrong aircraft", rule.metadata())
                )
                continue
            if rule.flight_phases is not None and state.flight_phase not in rule.flight_phases:
                diagnostics.append(
                    RuleDiagnostic(
                        rule.id,
                        "disabled",
                        f"phase={state.flight_phase.value}",
                        rule.metadata(),
                    )
                )
                continue
            missing = [
                field
                for field in sorted(rule.required_fields)
                if field not in telemetry or not telemetry[field].usable
            ]
            if missing:
                diagnostics.append(
                    RuleDiagnostic(
                        rule.id,
                        "disabled",
                        f"missing {', '.join(missing)}",
                        rule.metadata(),
                    )
                )
                continue
            if runtime.issue is not None:
                diagnostics.append(
                    RuleDiagnostic(
                        rule.id,
                        "ACTIVE",
                        runtime.issue.message,
                        rule.metadata(),
                    )
                )
                continue
            result = rule.evaluate(
                RuleContext(state=state, history=history, now=now, active=False)
            )
            diagnostics.append(
                RuleDiagnostic(
                    rule.id,
                    "pending" if result is not None else "inactive",
                    result.message if result is not None else "condition clear",
                    rule.metadata(),
                )
            )
        return tuple(diagnostics)

    def rule_by_id(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self.rules if rule.id == rule_id), None)

    def evaluate(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> tuple[RuleTransition, ...]:
        transitions: list[RuleTransition] = []
        for rule in self.rules:
            runtime = self._runtime[rule.id]
            if not self._applicable(rule, state):
                transition = self._deactivate(
                    runtime, now=now, transition_type=RuleTransitionType.DISABLED
                )
            else:
                result = rule.evaluate(
                    RuleContext(
                        state=state,
                        history=history,
                        now=now,
                        active=runtime.issue is not None,
                    )
                )
                transition = self._advance(rule, runtime, state, result, now=now)
            if transition is None:
                continue
            transitions.append(transition)
            self._emit(transition)
        return tuple(transitions)

    def reset(
        self, *, now: float = 0.0, emit: bool = True
    ) -> tuple[RuleTransition, ...]:
        transitions: list[RuleTransition] = []
        for runtime in self._runtime.values():
            transition = self._deactivate(
                runtime, now=now, transition_type=RuleTransitionType.DISABLED
            )
            runtime.last_notification_at = None
            if transition is not None:
                transitions.append(transition)
                if emit:
                    self._emit(transition)
        return tuple(transitions)

    @staticmethod
    def _applicable(rule: Rule, state: AircraftState) -> bool:
        if not state.connected or state.aircraft is None:
            return False
        if (
            rule.aircraft_names is not None
            and state.aircraft not in rule.aircraft_names
        ):
            return False
        if (
            rule.flight_phases is not None
            and state.flight_phase not in rule.flight_phases
        ):
            return False
        telemetry = state.telemetry()
        return all(
            name in telemetry and telemetry[name].usable
            for name in rule.required_fields
        )

    def _advance(
        self,
        rule: Rule,
        runtime: _RuleRuntime,
        state: AircraftState,
        result: RuleResult | None,
        *,
        now: float,
    ) -> RuleTransition | None:
        desired_active = result is not None
        current_active = runtime.issue is not None
        if desired_active == current_active:
            runtime.candidate_active = None
            runtime.candidate_since = None
            runtime.candidate_result = None
            if result is not None and runtime.issue is not None:
                runtime.issue = replace(
                    runtime.issue,
                    observed_at=now,
                    message=result.message,
                    explanation=result.explanation,
                    data=result.data,
                )
            return None

        if runtime.candidate_active != desired_active:
            runtime.candidate_active = desired_active
            runtime.candidate_since = now
        runtime.candidate_result = result
        delay = (
            rule.debounce_on_seconds if desired_active else rule.debounce_off_seconds
        )
        assert runtime.candidate_since is not None
        if now - runtime.candidate_since < delay:
            return None

        runtime.candidate_active = None
        runtime.candidate_since = None
        if desired_active:
            assert runtime.candidate_result is not None
            activated = self._activate(
                rule, runtime, state, runtime.candidate_result, now=now
            )
            runtime.candidate_result = None
            return activated
        runtime.candidate_result = None
        return self._deactivate(
            runtime, now=now, transition_type=RuleTransitionType.RESOLVED
        )

    @staticmethod
    def _activate(
        rule: Rule,
        runtime: _RuleRuntime,
        state: AircraftState,
        result: RuleResult,
        *,
        now: float,
    ) -> RuleTransition:
        assert state.aircraft is not None
        data = {**result.data, **rule.metadata()}
        issue = ActiveIssue(
            rule_id=rule.id,
            severity=rule.severity,
            aircraft=state.aircraft,
            flight_phase=state.flight_phase,
            activated_at=now,
            observed_at=now,
            message=result.message,
            explanation=result.explanation,
            data=data,
        )
        runtime.issue = issue
        eligible = (
            runtime.last_notification_at is None
            or now - runtime.last_notification_at >= rule.cooldown_seconds
        )
        if eligible:
            runtime.last_notification_at = now
        return RuleTransition(
            type=RuleTransitionType.ACTIVATED,
            issue=issue,
            timestamp=now,
            notification_eligible=eligible,
        )

    @staticmethod
    def _deactivate(
        runtime: _RuleRuntime,
        *,
        now: float,
        transition_type: RuleTransitionType,
    ) -> RuleTransition | None:
        runtime.candidate_active = None
        runtime.candidate_since = None
        runtime.candidate_result = None
        if runtime.issue is None:
            return None
        issue = replace(runtime.issue, observed_at=now)
        runtime.issue = None
        return RuleTransition(
            type=transition_type,
            issue=issue,
            timestamp=now,
            notification_eligible=False,
        )

    def _emit(self, transition: RuleTransition) -> None:
        LOGGER.info(
            "rule %s %s",
            transition.issue.rule_id,
            transition.type.value.lower(),
            extra={
                "event": f"rule_{transition.type.value.lower()}",
                "aircraft": transition.issue.aircraft,
                "rule_id": transition.issue.rule_id,
                "severity": transition.issue.severity.value,
            },
        )
        for callback in tuple(self._callbacks):
            callback(transition)


def _severity_rank(severity: Severity) -> int:
    return {
        Severity.INFO: 0,
        Severity.ADVISORY: 1,
        Severity.WARNING: 2,
        Severity.CRITICAL: 3,
    }[severity]
