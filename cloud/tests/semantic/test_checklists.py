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
    VerificationSource,
    VerificationType,
)
from dcs_copilot_cloud.state.history import StateHistory
from dcs_copilot_cloud.state.models import (
    AircraftState,
    FlightPhase,
    MasterArmState,
    TelemetryValue,
)


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
    unresolved_ids = {
        item.id for item in (*result.incomplete_items, *result.unconfirmed_items)
    }
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
    master_arm_item = next(
        item for item in result.items if item.id == "master_arm_safe"
    )
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


def test_latched_pre_start_does_not_regress_after_parking_brake_release() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    history = StateHistory()
    state = _cold_dark_state()
    state.parking_brake = TelemetryValue(True, available=True, updated_at=0.0)
    state.master_arm = TelemetryValue(
        MasterArmState.SAFE, available=True, updated_at=0.0
    )
    state.battery_on = TelemetryValue(True, available=True, updated_at=0.0)
    history.record(state, timestamp=0.0)
    engine.observe(state, history, now=0.0)

    state.parking_brake = TelemetryValue(False, available=True, updated_at=10.0)
    history.record(state, timestamp=10.0)
    result = engine.evaluate(
        state,
        history,
        now=10.0,
        checklist_id="fa18c_startup",
        stage_id="before-takeoff",
    )

    parking = next(item for item in result.items if item.id == "parking_brake")
    assert parking.status is ChecklistItemStatus.COMPLETE
    assert parking.actual is True


def test_live_pre_start_items_still_regress_after_parking_brake_latches() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    history = StateHistory()
    state = _cold_dark_state()
    state.parking_brake = TelemetryValue(True, available=True, updated_at=0.0)
    state.master_arm = TelemetryValue(
        MasterArmState.SAFE, available=True, updated_at=0.0
    )
    state.battery_on = TelemetryValue(True, available=True, updated_at=0.0)
    engine.observe(state, history, now=0.0)

    state.battery_on = TelemetryValue(False, available=True, updated_at=10.0)
    result = engine.evaluate(
        state,
        history,
        now=10.0,
        checklist_id="fa18c_startup",
        stage_id="before-taxi",
    )
    battery = next(item for item in result.items if item.id == "battery_on")
    assert battery.status is ChecklistItemStatus.INCOMPLETE


def test_default_guided_checklist_targets_before_taxi_and_resets_cleanly() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    engine.start("fa18c_startup")
    assert engine.session.stage_id == "before-taxi"

    engine.stop()
    assert engine.session.checklist_id is None

    engine.reset()
    assert engine.session.progress_checklist_id is None


def test_non_manual_checklist_item_cannot_be_voice_confirmed() -> None:
    engine = ChecklistEngine(fa18c_checklists())
    engine.start("fa18c_startup")
    with pytest.raises(ValueError, match="not manually confirmable"):
        engine.confirm_manual_item("parking_brake")


def _pilot_override_checklist() -> ChecklistDefinition:
    return ChecklistDefinition(
        id="pilot_override",
        aircraft="FA-18C_hornet",
        label="Pilot override",
        default_stage="only",
        stages=(
            ChecklistStage(
                id="only",
                label="Only",
                items=(
                    ChecklistItem(
                        id="apu_ready",
                        label="APU READY light",
                        verification=VerificationType.DERIVED,
                        condition={"apu_ready": True},
                    ),
                    ChecklistItem(
                        id="right_engine",
                        label="Crank right engine",
                        verification=VerificationType.STATE,
                        expected={"field": "engine_rpm_right", "greater_than": 60},
                    ),
                ),
            ),
        ),
    )


def test_explicit_pilot_report_overrides_current_item_and_advances() -> None:
    engine = ChecklistEngine([_pilot_override_checklist()])
    state = _cold_dark_state()
    history = StateHistory()
    engine.start("pilot_override")

    current = engine.next_item(state, history, now=10.0)
    assert current is not None
    assert current.id == "apu_ready"
    assert current.status is ChecklistItemStatus.INCOMPLETE

    previous, overridden = engine.confirm_current_item(
        "apu_ready", state, history, now=12.0
    )
    assert previous.id == "apu_ready"
    assert overridden is True

    result = engine.evaluate(state, history, now=13.0)
    apu = next(item for item in result.items if item.id == "apu_ready")
    assert apu.status is ChecklistItemStatus.COMPLETE
    assert apu.verification_source is VerificationSource.PILOT_OVERRIDE
    assert apu.observed_at == 12.0
    next_item = engine.next_item(state, history, now=13.0)
    assert next_item is not None
    assert next_item.id == "right_engine"


def test_pilot_override_cannot_skip_ahead_of_current_item() -> None:
    engine = ChecklistEngine([_pilot_override_checklist()])
    state = _cold_dark_state()
    history = StateHistory()
    engine.start("pilot_override")

    with pytest.raises(ValueError, match="only the current guided checklist item"):
        engine.confirm_current_item("right_engine", state, history, now=12.0)

    assert not engine.manual_item_confirmed("right_engine")
