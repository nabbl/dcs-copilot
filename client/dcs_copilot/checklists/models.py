"""Typed checklist definitions and deterministic results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dcs_copilot.rules.declarative import Condition


class ChecklistItemStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNCONFIRMED = "unconfirmed"
    NOT_APPLICABLE = "not_applicable"


class VerificationType(StrEnum):
    STATE = "state"
    ACTION = "action"
    DERIVED = "derived"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    id: str
    label: str
    verification: VerificationType
    expected: dict[str, Any] | None = None
    condition: Condition | None = None
    action_field: str | None = None
    applicable_if: Condition | None = None
    source_reference: str = "DCS-BIOS normalized telemetry"


@dataclass(frozen=True, slots=True)
class ChecklistStage:
    id: str
    label: str
    items: tuple[ChecklistItem, ...]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChecklistDefinition:
    id: str
    aircraft: str
    label: str
    stages: tuple[ChecklistStage, ...]


@dataclass(frozen=True, slots=True)
class ChecklistItemResult:
    id: str
    label: str
    status: ChecklistItemStatus
    expected: Any | None
    actual: Any | None
    reason: str
    verification_type: VerificationType
    observed_at: float | None = None


@dataclass(frozen=True, slots=True)
class ChecklistResult:
    checklist_id: str
    aircraft: str
    stage: str
    complete: bool
    complete_items: tuple[ChecklistItemResult, ...] = ()
    incomplete_items: tuple[ChecklistItemResult, ...] = ()
    unconfirmed_items: tuple[ChecklistItemResult, ...] = ()
    not_applicable_items: tuple[ChecklistItemResult, ...] = ()

    @property
    def items(self) -> tuple[ChecklistItemResult, ...]:
        return (
            *self.complete_items,
            *self.incomplete_items,
            *self.unconfirmed_items,
            *self.not_applicable_items,
        )


@dataclass(slots=True)
class ChecklistSession:
    checklist_id: str | None = None
    stage_id: str | None = None
    confirmed_manual_items: set[str] = field(default_factory=set)

    def start(self, checklist_id: str, stage_id: str | None = None) -> None:
        self.checklist_id = checklist_id
        self.stage_id = stage_id
        self.confirmed_manual_items.clear()

    def stop(self) -> None:
        self.checklist_id = None
        self.stage_id = None
        self.confirmed_manual_items.clear()
