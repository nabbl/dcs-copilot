from __future__ import annotations

import pytest
from dcs_copilot_cloud.coach.capabilities import DcsCapabilities
from dcs_copilot_cloud.coach.coordinator import CoachCoordinator
from dcs_copilot_cloud.coach.exercises.base import (
    ExerciseId,
    ExerciseState,
    ExerciseUnavailable,
)
from dcs_copilot_cloud.coach.models import (
    ReferenceObject,
    ReferenceObjectType,
    TelemetrySource,
)
from dcs_copilot_cloud.coach.spatial import Vec3


def _reference(object_type: ReferenceObjectType) -> ReferenceObject:
    return ReferenceObject(
        object_id=object_type.value.lower(),
        object_type=object_type,
        position=Vec3(0.0, 0.0, 0.0),
        velocity=Vec3(0.0, 0.0, 0.0),
        heading_deg=0.0,
        timestamp=1.0,
        source=TelemetrySource.DCS_EXPORT,
    )


@pytest.mark.parametrize(
    "exercise",
    [
        ExerciseId.LEFT_ECHELON,
        ExerciseId.CASE1_PATTERN,
        ExerciseId.CARRIER_APPROACH,
    ],
)
def test_world_object_exercises_cannot_start_when_export_is_blocked(
    exercise: ExerciseId,
) -> None:
    coach = CoachCoordinator()
    coach.update_capabilities(
        DcsCapabilities(ownship_export=True, world_object_export=False)
    )

    with pytest.raises(ExerciseUnavailable, match="world-object export is disabled"):
        coach.start(exercise, now=1.0)


def test_permission_loss_stops_active_exercise_and_discards_reference() -> None:
    coach = CoachCoordinator()
    coach.update_capabilities(
        DcsCapabilities(ownship_export=True, world_object_export=True)
    )
    coach.observations.replace_references(
        [_reference(ReferenceObjectType.LEAD_AIRCRAFT)]
    )
    status = coach.start(ExerciseId.LEFT_ECHELON, now=1.0)
    assert status.state is ExerciseState.ACTIVE

    coach.update_capabilities(
        DcsCapabilities(ownship_export=True, world_object_export=False)
    )

    assert coach.observations.references == ()
    assert coach.status().state is ExerciseState.UNAVAILABLE
    assert coach.status().exercise is ExerciseId.LEFT_ECHELON
    assert coach.relative_observations == ()
