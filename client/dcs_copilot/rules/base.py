"""Typed contracts shared by deterministic rules and their consumers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState, FlightPhase, TelemetryValue


class Severity(StrEnum):
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RuleTransitionType(StrEnum):
    ACTIVATED = "ACTIVATED"
    RESOLVED = "RESOLVED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class RuleResult:
    message: str
    explanation: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleContext:
    state: AircraftState
    history: StateHistory
    now: float
    active: bool

    def telemetry(self, field_name: str) -> TelemetryValue[Any] | None:
        return self.state.telemetry().get(field_name)


class Rule(ABC):
    id: str
    severity: Severity
    cooldown_seconds: float
    required_fields: frozenset[str]
    aircraft_names: frozenset[str] | None = None
    flight_phases: frozenset[FlightPhase] | None = None
    debounce_on_seconds: float = 0.0
    debounce_off_seconds: float = 0.0

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult | None:
        """Return the current violation, or None when the condition is clear."""


@dataclass(frozen=True, slots=True)
class ActiveIssue:
    rule_id: str
    severity: Severity
    aircraft: str
    flight_phase: FlightPhase
    activated_at: float
    observed_at: float
    message: str
    explanation: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuleTransition:
    type: RuleTransitionType
    issue: ActiveIssue
    timestamp: float
    notification_eligible: bool
