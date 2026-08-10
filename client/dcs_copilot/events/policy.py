"""Local policy deciding which deterministic events may reach cloud speech."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dcs_copilot.rules.base import RuleTransition, RuleTransitionType, Severity


class SpeechMode(StrEnum):
    MINIMAL = "MINIMAL"
    NORMAL = "NORMAL"
    COACH = "COACH"


@dataclass(frozen=True, slots=True)
class SpeechPolicy:
    mode: SpeechMode = SpeechMode.NORMAL
    normal_advisory_rules: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "FA18_PARKING_BRAKE_TAXI",
                "FA18_REFUELING_PROBE_LEFT_OUT",
            }
        )
    )

    def allows(self, transition: RuleTransition) -> bool:
        if transition.type is not RuleTransitionType.ACTIVATED:
            return False
        if not transition.notification_eligible:
            return False
        severity = transition.issue.severity
        if severity is Severity.CRITICAL:
            return True
        if self.mode is SpeechMode.MINIMAL:
            return False
        if severity is Severity.WARNING:
            return True
        if severity is Severity.ADVISORY:
            return (
                self.mode is SpeechMode.COACH
                or transition.issue.rule_id in self.normal_advisory_rules
            )
        return self.mode is SpeechMode.COACH
