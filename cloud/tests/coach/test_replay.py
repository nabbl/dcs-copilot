from __future__ import annotations

from pathlib import Path

from dcs_copilot_cloud.coach.exercises.base import ExerciseId
from dcs_copilot_cloud.coach.replay import CoachRecordingWriter, replay_exercise
from dcs_copilot_protocol import (
    CoachCapabilitiesPayload,
    CoachReferencePayload,
    CoachTelemetry,
    CoachVec3,
    OwnshipPayload,
)


def _frame(sequence: int, t: float, *, y: float) -> CoachTelemetry:
    return CoachTelemetry(
        sequence=sequence,
        observed_at_ms=round(t * 1000),
        capabilities=CoachCapabilitiesPayload(True, True, False, True),
        ownship=OwnshipPayload(
            position=CoachVec3(-22.0, y, -18.0),
            velocity=CoachVec3(0.0, 0.0, 0.0),
            heading_deg=0.0,
        ),
        references=(
            CoachReferencePayload(
                object_id="lead",
                object_type="LEAD_AIRCRAFT",
                position=CoachVec3(0.0, 0.0, 0.0),
                velocity=CoachVec3(0.0, 0.0, 0.0),
                heading_deg=0.0,
            ),
        ),
    )


def test_normalized_recording_replays_through_the_live_exercise_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "formation.jsonl"
    with CoachRecordingWriter(path) as writer:
        writer.write(0.0, _frame(0, 0.0, y=0.0))
        writer.write(2.0, _frame(1, 2.0, y=-4.0))
        writer.write(4.0, _frame(2, 4.0, y=-8.0))

    debrief = replay_exercise(path, ExerciseId.LEFT_ECHELON)

    assert debrief["exercise"] == "LEFT_ECHELON"
    assert debrief["samples"] == 3
    assert debrief["dominant_error_axis"] == "vertical"
