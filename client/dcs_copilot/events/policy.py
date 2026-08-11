"""Local policy deciding which deterministic events may reach cloud speech."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dcs_copilot.rules.base import CopilotMode, RuleTransition, RuleTransitionType, Severity


class SpeechMode(StrEnum):
    MINIMAL = "MINIMAL"
    NORMAL = "NORMAL"
    COACH = "COACH"


@dataclass(frozen=True, slots=True)
class SpeechPolicy:
    mode: SpeechMode = SpeechMode.NORMAL
    normal_advisory_rules: frozenset[str] = field(default_factory=frozenset)

    def allows(self, transition: RuleTransition) -> bool:
        if transition.type is not RuleTransitionType.ACTIVATED:
            return False
        if not transition.notification_eligible:
            return False
        if transition.issue.data.get("proactive") is False:
            return False
        minimum_mode_raw = transition.issue.data.get("minimum_mode")
        if isinstance(minimum_mode_raw, str):
            try:
                return _mode_rank(self.mode) >= _mode_rank(CopilotMode(minimum_mode_raw))
            except ValueError:
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


def _mode_rank(mode: SpeechMode | CopilotMode) -> int:
    return {
        "MINIMAL": 0,
        "NORMAL": 1,
        "COACH": 2,
    }[mode.value]
