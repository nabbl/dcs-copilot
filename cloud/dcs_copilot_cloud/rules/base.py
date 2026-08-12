"""Typed contracts shared by deterministic rules and their consumers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..state.history import StateHistory
from ..state.models import AircraftState, FlightPhase, TelemetryValue


class Severity(StrEnum):
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class CopilotMode(StrEnum):
    MINIMAL = "MINIMAL"
    NORMAL = "NORMAL"
    COACH = "COACH"


class RuleFeasibility(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class FalsePositiveRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


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
    category: str = "general"
    minimum_mode: CopilotMode = CopilotMode.NORMAL
    severity: Severity
    feasibility: RuleFeasibility = RuleFeasibility.A
    false_positive_risk: FalsePositiveRisk = FalsePositiveRisk.LOW
    description: str = ""
    source_reference: str = "Backend normalized telemetry"
    cooldown_seconds: float
    required_fields: frozenset[str]
    aircraft_names: frozenset[str] | None = None
    flight_phases: frozenset[FlightPhase] | None = None
    debounce_on_seconds: float = 0.0
    debounce_off_seconds: float = 0.0

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult | None:
        """Return the current violation, or None when the condition is clear."""

    def metadata(self) -> dict[str, str]:
        return {
            "category": self.category,
            "minimum_mode": self.minimum_mode.value,
            "feasibility": self.feasibility.value,
            "false_positive_risk": self.false_positive_risk.value,
            "description": self.description,
            "source_reference": self.source_reference,
        }


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
