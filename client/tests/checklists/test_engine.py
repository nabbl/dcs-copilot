from __future__ import annotations

from dcs_copilot.checklists import (
    ChecklistDefinition,
    ChecklistEngine,
    ChecklistItem,
    ChecklistItemStatus,
    ChecklistStage,
    VerificationType,
)
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState, TelemetryValue


def tv(value):
    return TelemetryValue(value=value, available=True, updated_at=1.0, source="test")


def engine_for(items: tuple[ChecklistItem, ...]) -> ChecklistEngine:
    return ChecklistEngine(
        [
            ChecklistDefinition(
                id="test",
                aircraft="FA-18C_hornet",
                label="Test",
                stages=(ChecklistStage("stage", "Stage", items),),
            )
        ]
    )


def state(**values) -> AircraftState:
    result = AircraftState(aircraft="FA-18C_hornet", connected=True)
    for name, value in values.items():
        setattr(result, name, tv(value))
    return result


def test_state_verification_distinguishes_complete_incomplete_and_unconfirmed() -> None:
    item = ChecklistItem(
        "obogs",
        "OBOGS",
        VerificationType.STATE,
        expected={"field": "obogs_on", "equals": True},
    )
    engine = engine_for((item,))
    history = StateHistory()

    complete = engine.evaluate(state(obogs_on=True), history, now=1)
    assert complete.complete_items[0].status is ChecklistItemStatus.COMPLETE

    incomplete = engine.evaluate(state(obogs_on=False), history, now=1)
    assert incomplete.incomplete_items[0].actual is False

    unavailable = engine.evaluate(state(), history, now=1)
    assert unavailable.unconfirmed_items[0].reason == "obogs_on is unavailable"


def test_state_verification_supports_negative_expectations() -> None:
    item = ChecklistItem(
        "ins",
        "INS",
        VerificationType.STATE,
        expected={"field": "ins_mode", "not_equals": "OFF"},
    )
    engine = engine_for((item,))

    assert engine.evaluate(state(ins_mode="GND"), StateHistory(), now=1).complete
    assert engine.evaluate(state(ins_mode="OFF"), StateHistory(), now=1).incomplete_items


def test_state_verification_supports_allowed_values() -> None:
    item = ChecklistItem(
        "ins",
        "INS",
        VerificationType.STATE,
        expected={"field": "ins_mode", "one_of": ("CV", "GND", "NAV", "IFA")},
    )
    engine = engine_for((item,))

    assert engine.evaluate(state(ins_mode="GND"), StateHistory(), now=1).complete
    assert engine.evaluate(state(ins_mode="TEST"), StateHistory(), now=1).incomplete_items


def test_action_verification_uses_state_history_transitions() -> None:
    item = ChecklistItem(
        "takeoff_trim",
        "Takeoff trim",
        VerificationType.ACTION,
        action_field="takeoff_trim_pressed",
    )
    engine = engine_for((item,))
    history = StateHistory()

    assert engine.evaluate(state(), history, now=1).unconfirmed_items

    trimmed = state(takeoff_trim_pressed=True)
    history.record(trimmed, timestamp=2)
    result = engine.evaluate(trimmed, history, now=2)
    assert result.complete_items[0].observed_at == 2


def test_derived_manual_and_conditional_items() -> None:
    derived = ChecklistItem(
        "launch_config",
        "Launch config",
        VerificationType.DERIVED,
        condition={"all": [{"obogs_on": True}, {"ejection_seat_armed": True}]},
    )
    manual = ChecklistItem("helmet", "Helmet", VerificationType.MANUAL)
    conditional = ChecklistItem(
        "probe",
        "Probe",
        VerificationType.STATE,
        expected={"field": "refueling_probe", "equals": False},
        applicable_if={"airborne": True},
    )
    engine = engine_for((derived, manual, conditional))
    current = state(obogs_on=True, ejection_seat_armed=True, airborne=False)
    result = engine.evaluate(current, StateHistory(), now=1)
    assert result.complete_items[0].id == "launch_config"
    assert result.unconfirmed_items[0].id == "helmet"
    assert result.not_applicable_items[0].id == "probe"

    engine.confirm_manual_item("helmet")
    confirmed = engine.evaluate(current, StateHistory(), now=1)
    assert {item.id for item in confirmed.complete_items} == {"launch_config", "helmet"}


def test_stage_evaluation_includes_transitive_dependencies() -> None:
    engine = ChecklistEngine(
        [
            ChecklistDefinition(
                id="startup",
                aircraft="FA-18C_hornet",
                label="Startup",
                stages=(
                    ChecklistStage(
                        "power",
                        "Power",
                        (
                            ChecklistItem(
                                "battery",
                                "Battery",
                                VerificationType.STATE,
                                expected={"field": "battery_on", "equals": True},
                            ),
                        ),
                    ),
                    ChecklistStage(
                        "engines",
                        "Engines",
                        (
                            ChecklistItem(
                                "left_engine",
                                "Left engine",
                                VerificationType.STATE,
                                expected={
                                    "field": "engine_rpm_left",
                                    "greater_than": 60,
                                },
                            ),
                        ),
                        depends_on=("power",),
                    ),
                    ChecklistStage(
                        "before-taxi",
                        "Before taxi",
                        (),
                        depends_on=("engines",),
                    ),
                ),
                default_stage="before-taxi",
            )
        ]
    )

    result = engine.evaluate(
        state(battery_on=False, engine_rpm_left=0), StateHistory(), now=1
    )

    assert result.stage == "before-taxi"
    assert [item.id for item in result.incomplete_items] == [
        "battery",
        "left_engine",
    ]
