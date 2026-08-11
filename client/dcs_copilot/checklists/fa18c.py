"""Initial data-driven F/A-18C checklist definitions."""

from __future__ import annotations

from dcs_copilot.state.models import CanopyState, FlapState, GearState, MasterArmState

from .models import (
    ChecklistDefinition,
    ChecklistItem,
    ChecklistStage,
    VerificationType,
)


def fa18c_checklists() -> tuple[ChecklistDefinition, ...]:
    return (
        ChecklistDefinition(
            id="fa18c_startup",
            aircraft="FA-18C_hornet",
            label="F/A-18C Startup",
            stages=(
                ChecklistStage(
                    id="pre-start",
                    label="PRE START",
                    items=(
                        ChecklistItem(
                            id="parking_brake",
                            label="Parking brake",
                            verification=VerificationType.STATE,
                            expected={"field": "parking_brake", "equals": True},
                        ),
                        ChecklistItem(
                            id="master_arm_safe",
                            label="Master Arm",
                            verification=VerificationType.STATE,
                            expected={
                                "field": "master_arm",
                                "equals": MasterArmState.SAFE,
                            },
                        ),
                    ),
                ),
                ChecklistStage(
                    id="engine-start",
                    label="ENGINE START",
                    items=(
                        ChecklistItem(
                            id="left_engine_running",
                            label="Left engine",
                            verification=VerificationType.STATE,
                            expected={"field": "engine_rpm_left", "greater_than": 60},
                        ),
                        ChecklistItem(
                            id="right_engine_running",
                            label="Right engine",
                            verification=VerificationType.STATE,
                            expected={"field": "engine_rpm_right", "greater_than": 60},
                        ),
                    ),
                ),
                ChecklistStage(
                    id="post-start",
                    label="POST START",
                    items=(
                        ChecklistItem(
                            id="obogs_on",
                            label="OBOGS",
                            verification=VerificationType.STATE,
                            expected={"field": "obogs_on", "equals": True},
                        ),
                        ChecklistItem(
                            id="master_caution_clear",
                            label="Master caution",
                            verification=VerificationType.STATE,
                            expected={"field": "master_caution", "equals": False},
                        ),
                    ),
                    depends_on=("engine-start",),
                ),
                ChecklistStage(
                    id="before-taxi",
                    label="BEFORE TAXI",
                    items=(
                        ChecklistItem(
                            id="obogs_on",
                            label="OBOGS",
                            verification=VerificationType.STATE,
                            expected={"field": "obogs_on", "equals": True},
                        ),
                        ChecklistItem(
                            id="ejection_seat_armed",
                            label="Ejection seat",
                            verification=VerificationType.STATE,
                            expected={"field": "ejection_seat_armed", "equals": True},
                        ),
                        ChecklistItem(
                            id="canopy_closed",
                            label="Canopy",
                            verification=VerificationType.STATE,
                            expected={
                                "field": "canopy_state",
                                "equals": CanopyState.CLOSED,
                            },
                        ),
                        ChecklistItem(
                            id="takeoff_trim",
                            label="Takeoff trim",
                            verification=VerificationType.ACTION,
                            action_field="takeoff_trim_pressed",
                            source_reference="DCS-BIOS T/O TRIM button transition",
                        ),
                        ChecklistItem(
                            id="master_caution_clear",
                            label="Master caution",
                            verification=VerificationType.STATE,
                            expected={"field": "master_caution", "equals": False},
                        ),
                    ),
                    depends_on=("post-start",),
                ),
                ChecklistStage(
                    id="before-takeoff",
                    label="BEFORE TAKEOFF",
                    items=(
                        ChecklistItem(
                            id="flaps_half",
                            label="Flaps",
                            verification=VerificationType.STATE,
                            expected={"field": "flap_position", "equals": FlapState.HALF},
                        ),
                        ChecklistItem(
                            id="gear_down",
                            label="Landing gear",
                            verification=VerificationType.STATE,
                            expected={"field": "gear_position", "equals": GearState.DOWN},
                        ),
                        ChecklistItem(
                            id="hook_up",
                            label="Hook",
                            verification=VerificationType.STATE,
                            expected={"field": "hook_position", "equals": False},
                        ),
                        ChecklistItem(
                            id="speedbrake_retracted",
                            label="Speedbrake",
                            verification=VerificationType.STATE,
                            expected={"field": "speed_brake", "less_than_or_equal": 0.05},
                        ),
                        ChecklistItem(
                            id="master_arm_safe",
                            label="Master Arm",
                            verification=VerificationType.STATE,
                            expected={
                                "field": "master_arm",
                                "equals": MasterArmState.SAFE,
                            },
                        ),
                    ),
                    depends_on=("before-taxi",),
                ),
                ChecklistStage(
                    id="carrier-launch",
                    label="CARRIER LAUNCH",
                    items=(
                        ChecklistItem(
                            id="wings_spread",
                            label="Wings",
                            verification=VerificationType.STATE,
                            expected={"field": "wing_fold_spread", "equals": True},
                        ),
                        ChecklistItem(
                            id="launch_bar_down",
                            label="Launch bar",
                            verification=VerificationType.STATE,
                            expected={"field": "launch_bar_deployed", "equals": True},
                        ),
                        ChecklistItem(
                            id="carrier_launch_config",
                            label="Carrier launch configuration",
                            verification=VerificationType.DERIVED,
                            condition={
                                "all": [
                                    {"flap_position": FlapState.HALF},
                                    {"gear_position": GearState.DOWN},
                                    {"hook_position": False},
                                    {"ejection_seat_armed": True},
                                    {"obogs_on": True},
                                    {"wing_fold_spread": True},
                                ]
                            },
                        ),
                    ),
                    depends_on=("before-takeoff",),
                ),
            ),
        ),
    )
