"""Tests for the cloud checklist engine: dependency chains and validation."""

from __future__ import annotations

import pytest

from dcs_copilot_cloud.checklists.engine import ChecklistEngine
from dcs_copilot_cloud.checklists.fa18c import fa18c_checklists
from dcs_copilot_cloud.checklists.models import (
    ChecklistDefinition,
    ChecklistItem,
    ChecklistItemStatus,
    ChecklistStage,
    VerificationType,
)
from dcs_copilot_cloud.state.history import StateHistory
from dcs_copilot_cloud.state.models import AircraftState, FlightPhase


def _cold_dark_state() -> AircraftState:
    state = AircraftState(aircraft="FA-18C_hornet", connected=True)
    state.flight_phase = FlightPhase.COLD_DARK
    return state


def test_before_taxi_includes_missing_battery_apu_engines_when_cold_and_dark() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    state = _cold_dark_state()
    history = StateHistory()
    result = engine.evaluate(
        state, history, now=0.0, checklist_id="fa18c_startup", stage_id="before-taxi"
    )
    assert not result.complete
    unresolved_ids = {item.id for item in (*result.incomplete_items, *result.unconfirmed_items)}
    assert "battery_on" in unresolved_ids
    assert "apu_ready" in unresolved_ids
    assert "left_engine_running" in unresolved_ids
    assert "right_engine_running" in unresolved_ids


def test_before_taxi_transitively_includes_earlier_stage_items() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    state = _cold_dark_state()
    history = StateHistory()
    result = engine.evaluate(
        state, history, now=0.0, checklist_id="fa18c_startup", stage_id="before-taxi"
    )
    all_ids = {item.id for item in result.items}
    # pre-start
    assert "parking_brake" in all_ids
    assert "master_arm_safe" in all_ids
    assert "battery_on" in all_ids
    # engine-start
    assert "apu_ready" in all_ids
    assert "left_engine_running" in all_ids
    assert "right_engine_running" in all_ids
    # post-start
    assert "obogs_on" in all_ids
    assert "left_generator_normal" in all_ids
    assert "master_caution_clear" in all_ids
    # before-taxi itself
    assert "ejection_seat_armed" in all_ids
    assert "canopy_closed" in all_ids
    assert "takeoff_trim" in all_ids


def test_default_stage_is_before_taxi() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    state = _cold_dark_state()
    history = StateHistory()
    result = engine.evaluate(state, history, now=0.0, checklist_id="fa18c_startup")
    assert result.stage == "before-taxi"


def test_stale_required_telemetry_is_unconfirmed_not_complete() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    state = _cold_dark_state()
    history = StateHistory()
    # master_arm_safe references "master_arm" which is unavailable entirely -> unconfirmed.
    result = engine.evaluate(
        state, history, now=0.0, checklist_id="fa18c_startup", stage_id="pre-start"
    )
    master_arm_item = next(item for item in result.items if item.id == "master_arm_safe")
    assert master_arm_item.status is ChecklistItemStatus.UNCONFIRMED
    assert not result.complete


def test_duplicate_stage_id_raises() -> None:
    stage = ChecklistStage(id="dup", label="Dup", items=())
    definition = ChecklistDefinition(
        id="bad",
        aircraft="FA-18C_hornet",
        label="Bad",
        stages=(stage, stage),
    )
    with pytest.raises(ValueError, match="duplicate stage id"):
        ChecklistEngine([definition])


def test_duplicate_item_id_raises() -> None:
    item = ChecklistItem(
        id="dup_item",
        label="Dup item",
        verification=VerificationType.STATE,
        expected={"field": "battery_on", "equals": True},
    )
    stage = ChecklistStage(id="only", label="Only", items=(item, item))
    definition = ChecklistDefinition(
        id="bad",
        aircraft="FA-18C_hornet",
        label="Bad",
        stages=(stage,),
    )
    with pytest.raises(ValueError, match="duplicate item id"):
        ChecklistEngine([definition])


def test_missing_dependency_reference_raises() -> None:
    stage = ChecklistStage(id="only", label="Only", items=(), depends_on=("ghost",))
    definition = ChecklistDefinition(
        id="bad",
        aircraft="FA-18C_hornet",
        label="Bad",
        stages=(stage,),
    )
    with pytest.raises(ValueError, match="unknown dependency"):
        ChecklistEngine([definition])


def test_dependency_cycle_raises() -> None:
    stage_a = ChecklistStage(id="a", label="A", items=(), depends_on=("b",))
    stage_b = ChecklistStage(id="b", label="B", items=(), depends_on=("a",))
    definition = ChecklistDefinition(
        id="bad",
        aircraft="FA-18C_hornet",
        label="Bad",
        stages=(stage_a, stage_b),
    )
    with pytest.raises(ValueError, match="cyclic checklist stage dependency"):
        ChecklistEngine([definition])
