from __future__ import annotations

import pytest
from dcs_copilot_cloud.coach.exercises.base import ExerciseState
from dcs_copilot_cloud.coach.exercises.formation import (
    FormationExercise,
    FormationProfile,
    FormationTarget,
    FormationTolerance,
    FormationZone,
)
from dcs_copilot_cloud.coach.models import (
    ObservedValue,
    OwnshipState,
    ReferenceObject,
    ReferenceObjectType,
    TelemetrySource,
)
from dcs_copilot_cloud.coach.spatial import Vec3

SOURCE = TelemetrySource.DCS_EXPORT


def _ownship(
    position: Vec3, timestamp: float, velocity: Vec3 | None = None
) -> OwnshipState:
    return OwnshipState(
        position=ObservedValue.observed(position, source=SOURCE, timestamp=timestamp),
        velocity=ObservedValue.observed(
            velocity or Vec3(0.0, 0.0, 0.0), source=SOURCE, timestamp=timestamp
        ),
        heading_deg=ObservedValue.observed(0.0, source=SOURCE, timestamp=timestamp),
        pitch_deg=ObservedValue.observed(0.0, source=SOURCE, timestamp=timestamp),
        roll_deg=ObservedValue.observed(0.0, source=SOURCE, timestamp=timestamp),
        timestamp=timestamp,
    )


def _lead(timestamp: float) -> ReferenceObject:
    return ReferenceObject(
        object_id="lead",
        object_type=ReferenceObjectType.LEAD_AIRCRAFT,
        position=Vec3(0.0, 0.0, 0.0),
        velocity=Vec3(0.0, 0.0, 0.0),
        heading_deg=0.0,
        timestamp=timestamp,
        source=SOURCE,
    )


def _profile() -> FormationProfile:
    return FormationProfile(
        aircraft="TEST",
        training_profile="test",
        target=FormationTarget(forward_m=-30.0, right_m=-20.0, up_m=0.0),
        tolerance=FormationTolerance(good_m=2.0, acceptable_m=5.0),
        outside_hold_seconds=1.5,
        good_hold_seconds=2.0,
        speech_cooldown_seconds=1.0,
    )


def test_formation_feedback_uses_hysteresis_and_semantic_directions() -> None:
    exercise = FormationExercise(_profile(), started_at=0.0)

    assert (
        exercise.update(_ownship(Vec3(-40.0, 0.0, -20.0), 0.0), _lead(0.0), now=0.0)
        == ()
    )
    feedback = exercise.update(
        _ownship(Vec3(-40.0, 0.0, -20.0), 1.6), _lead(1.6), now=1.6
    )
    assert [item.message for item in feedback] == ["Come forward a little."]
    assert exercise.last_sample is not None
    assert exercise.last_sample.zone is FormationZone.OUTSIDE

    assert (
        exercise.update(_ownship(Vec3(-30.0, 0.0, -20.0), 2.0), _lead(2.0), now=2.0)
        == ()
    )
    feedback = exercise.update(
        _ownship(Vec3(-30.0, 0.0, -20.0), 4.1), _lead(4.1), now=4.1
    )
    assert [item.message for item in feedback] == ["Good position. Hold that."]


def test_formation_debrief_statistics_are_deterministic() -> None:
    exercise = FormationExercise(_profile(), started_at=0.0)
    exercise.update(_ownship(Vec3(-30.0, 0.0, -20.0), 0.0), _lead(0.0), now=0.0)
    exercise.update(_ownship(Vec3(-30.0, -4.0, -20.0), 2.0), _lead(2.0), now=2.0)
    exercise.update(_ownship(Vec3(-30.0, -8.0, -20.0), 4.0), _lead(4.0), now=4.0)

    debrief = exercise.stop(now=4.0)

    assert debrief["duration_seconds"] == pytest.approx(4.0)
    assert debrief["samples"] == 3
    assert debrief["time_good_seconds"] == pytest.approx(2.0)
    assert debrief["time_acceptable_seconds"] == pytest.approx(2.0)
    assert debrief["dominant_error_axis"] == "vertical"
    assert debrief["mean_vertical_error_m"] == pytest.approx(-4.0)
    assert debrief["max_position_error_m"] == pytest.approx(8.0)


def test_formation_pauses_on_stale_reference() -> None:
    exercise = FormationExercise(_profile(), started_at=0.0, stale_after=1.0)

    feedback = exercise.update(
        _ownship(Vec3(-40.0, 0.0, -20.0), 2.0), _lead(0.0), now=2.0
    )

    assert feedback == ()
    assert exercise.state is ExerciseState.PAUSED
    assert exercise.last_sample is None
