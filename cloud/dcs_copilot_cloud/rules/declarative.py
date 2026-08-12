"""Declarative deterministic rules and local condition evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..state.models import AircraftState, FlightPhase
from .base import (
    CopilotMode,
    FalsePositiveRisk,
    Rule,
    RuleContext,
    RuleFeasibility,
    RuleResult,
    Severity,
)

Condition = dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    id: str
    aircraft: str
    severity: Severity
    required_fields: frozenset[str]
    condition: Condition
    message: str
    category: str = "configuration"
    minimum_mode: CopilotMode = CopilotMode.NORMAL
    feasibility: RuleFeasibility = RuleFeasibility.A
    false_positive_risk: FalsePositiveRisk = FalsePositiveRisk.LOW
    description: str = ""
    source_reference: str = "Backend normalized telemetry"
    explanation: str | None = None
    phases: frozenset[FlightPhase] | None = None
    activation_delay: float = 0.0
    resolution_delay: float = 0.0
    cooldown: float = 30.0
    proactive: bool = True
    data_fields: frozenset[str] = field(default_factory=frozenset)


class DeclarativeRule(Rule):
    def __init__(self, definition: RuleDefinition) -> None:
        self.definition = definition
        self.id = definition.id
        self.category = definition.category
        self.minimum_mode = definition.minimum_mode
        self.severity = definition.severity
        self.feasibility = definition.feasibility
        self.false_positive_risk = definition.false_positive_risk
        self.description = definition.description or definition.explanation or definition.message
        self.source_reference = definition.source_reference
        self.cooldown_seconds = definition.cooldown
        self.required_fields = definition.required_fields
        self.aircraft_names = frozenset({definition.aircraft})
        self.flight_phases = definition.phases
        self.debounce_on_seconds = definition.activation_delay
        self.debounce_off_seconds = definition.resolution_delay

    def evaluate(self, context: RuleContext) -> RuleResult | None:
        if not evaluate_condition(self.definition.condition, context):
            return None
        data = {
            field: _json_value(value)
            for field in self.definition.data_fields
            if (value := _field_value(context.state, field)) is not None
        }
        data["proactive"] = self.definition.proactive
        return RuleResult(
            message=self.definition.message,
            explanation=self.definition.explanation or self.definition.message,
            data=data,
        )


def evaluate_condition(condition: Condition, context: RuleContext) -> bool:
    if "all" in condition:
        return all(evaluate_condition(item, context) for item in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(item, context) for item in condition["any"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], context)
    if "available" in condition:
        telemetry = context.telemetry(str(condition["available"]))
        return telemetry is not None and telemetry.usable
    if "changed_to" in condition:
        spec = condition["changed_to"]
        return context.history.changed_within(
            str(spec["field"]),
            old_value=spec.get("from"),
            new_value=_coerce_expected(spec["value"]),
            seconds=float(spec.get("seconds", 60.0)),
            now=context.now,
        )
    if "changed_from" in condition:
        spec = condition["changed_from"]
        return any(
            transition.old_value == _coerce_expected(spec["value"])
            for transition in context.history.transitions(
                str(spec["field"]),
                since=context.now - float(spec.get("seconds", 60.0)),
            )
        )
    if "duration" in condition:
        spec = condition["duration"]
        seconds = float(spec["seconds"])
        nested = spec["condition"]
        fields = _condition_fields(nested)
        return evaluate_condition(nested, context) and not any(
            transition.field in fields
            for transition in context.history.transitions(since=context.now - seconds)
        )
    for field, expected in condition.items():
        value = _field_value(context.state, field)
        if value is None:
            return False
        if isinstance(expected, dict):
            if "equals" in expected and not _values_equal(value, expected["equals"]):
                return False
            if "not_equals" in expected and _values_equal(value, expected["not_equals"]):
                return False
            if "greater_than" in expected and not (
                isinstance(value, (int, float)) and value > float(expected["greater_than"])
            ):
                return False
            if "less_than" in expected and not (
                isinstance(value, (int, float)) and value < float(expected["less_than"])
            ):
                return False
            continue
        if not _values_equal(value, expected):
            return False
    return True


def _field_value(state: AircraftState, field: str) -> Any:
    telemetry = state.telemetry().get(field)
    if telemetry is None or not telemetry.usable:
        return None
    return telemetry.value


def _coerce_expected(value: Any) -> Any:
    if isinstance(value, str):
        for enum_type in (FlightPhase,):
            try:
                return enum_type(value)
            except ValueError:
                pass
    return value


def _values_equal(actual: Any, expected: Any) -> bool:
    if hasattr(actual, "value") and isinstance(expected, str):
        return actual.value == expected
    return actual == _coerce_expected(expected)


def _condition_fields(condition: Condition) -> frozenset[str]:
    fields: set[str] = set()
    if "all" in condition:
        for item in condition["all"]:
            fields.update(_condition_fields(item))
    elif "any" in condition:
        for item in condition["any"]:
            fields.update(_condition_fields(item))
    elif "not" in condition:
        fields.update(_condition_fields(condition["not"]))
    else:
        fields.update(
            key
            for key in condition
            if key not in {"available", "changed_to", "changed_from", "duration"}
        )
        for key in ("available", "changed_to", "changed_from"):
            if key in condition:
                spec = condition[key]
                fields.add(str(spec["field"] if isinstance(spec, dict) else spec))
    return frozenset(fields)


def _json_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


__all__ = [
    "Condition",
    "DeclarativeRule",
    "RuleDefinition",
    "evaluate_condition",
]
