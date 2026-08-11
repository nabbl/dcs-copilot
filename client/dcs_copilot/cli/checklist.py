"""CLI diagnostics for deterministic checklist evaluation."""

from __future__ import annotations

import asyncio
import time

from dcs_copilot.config import Settings
from dcs_copilot.checklists import ChecklistItemResult, ChecklistItemStatus
from dcs_copilot.cli.rules import _state_store


def run_checklist_status(settings: Settings, wait: float, stage: str | None) -> int:
    store = asyncio.run(_state_store(settings, wait))
    if store is None:
        return 2
    try:
        result = store.checklist_engine.evaluate(
            store.current,
            store.history,
            now=time.monotonic(),
            stage_id=stage,
        )
    except ValueError as exc:
        print(f"Checklist failed: {exc}")
        return 2
    print(f"{result.aircraft} — {result.stage.upper()}\n")
    for item in result.items:
        print(f"{_mark(item):1} {item.label:28} {item.status.value.upper()}")
    print(f"\nStatus: {'COMPLETE' if result.complete else 'NOT COMPLETE'}")
    return 0 if result.complete else 1


def run_checklist_explain(
    settings: Settings,
    wait: float,
    item_id: str,
    stage: str | None,
) -> int:
    store = asyncio.run(_state_store(settings, wait))
    if store is None:
        return 2
    try:
        item = store.checklist_engine.explain_item(
            item_id,
            store.current,
            store.history,
            now=time.monotonic(),
            stage_id=stage,
        )
    except ValueError as exc:
        print(f"Checklist explain failed: {exc}")
        return 2
    print(item.label)
    print()
    print(f"Status: {item.status.value.upper()}")
    print(f"Verification: {item.verification_type.value.upper()}")
    print(f"Expected: {item.expected}")
    print(f"Actual: {item.actual}")
    print(f"Reason: {item.reason}")
    if item.observed_at is not None:
        print(f"Observed at: {item.observed_at:.3f}")
    return 0


def _mark(item: ChecklistItemResult) -> str:
    return {
        ChecklistItemStatus.COMPLETE: "✓",
        ChecklistItemStatus.INCOMPLETE: "✗",
        ChecklistItemStatus.UNCONFIRMED: "?",
        ChecklistItemStatus.NOT_APPLICABLE: "-",
    }[item.status]


__all__ = ["run_checklist_explain", "run_checklist_status"]
