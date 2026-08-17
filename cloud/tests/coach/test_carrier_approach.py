from __future__ import annotations

import math

import pytest
from dcs_copilot_cloud.coach.exercises.carrier_approach import (
    CarrierApproachExercise,
    CarrierApproachProfile,
    GlidepathState,
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


def _carrier(timestamp: float) -> ReferenceObject:
    return ReferenceObject(
        object_id="cvn-71",
        object_type=ReferenceObjectType.CARRIER,
        position=Vec3(0.0, 0.0, 0.0),
        velocity=Vec3(10.0, 0.0, 0.0),
        heading_deg=0.0,
        timestamp=timestamp,
        source=SOURCE,
        name="Theodore Roosevelt",
    )


def _ownship(*, distance_m: float, error_m: float, timestamp: float) -> OwnshipState:
    desired = math.tan(math.radians(3.5)) * distance_m
    return OwnshipState(
        position=ObservedValue.observed(
            Vec3(-distance_m, desired + error_m, 0.0),
            source=SOURCE,
            timestamp=timestamp,
        ),
        velocity=ObservedValue.observed(
            Vec3(80.0, -3.0, 0.0), source=SOURCE, timestamp=timestamp
        ),
        heading_deg=ObservedValue.observed(0.0, source=SOURCE, timestamp=timestamp),
        timestamp=timestamp,
    )


def _profile() -> CarrierApproachProfile:
    return CarrierApproachProfile(
        name="test",
        glidepath_deg=3.5,
        aimpoint_offset_m=0.0,
        acceptable_vertical_error_m=5.0,
        acceptable_lineup_error_m=8.0,
        low_error_m=15.0,
        trend_window_seconds=5.0,
        feedback_hold_seconds=1.0,
        speech_cooldown_seconds=3.0,
    )


def test_carrier_approach_detects_low_diverging_and_recovering_trends() -> None:
    exercise = CarrierApproachExercise(_profile(), started_at=0.0)
    exercise.update(
        _ownship(distance_m=1000.0, error_m=-20.0, timestamp=0.0),
        _carrier(0.0),
        now=0.0,
    )
    exercise.update(
        _ownship(distance_m=900.0, error_m=-30.0, timestamp=1.0), _carrier(1.0), now=1.0
    )
    assert exercise.last_sample is not None
    assert exercise.last_sample.glidepath_state is GlidepathState.DIVERGING_LOW

    exercise.update(
        _ownship(distance_m=800.0, error_m=-10.0, timestamp=2.0), _carrier(2.0), now=2.0
    )
    assert exercise.last_sample is not None
    assert exercise.last_sample.glidepath_state is GlidepathState.RECOVERING


def test_carrier_approach_speaks_once_then_stays_quiet_during_recovery() -> None:
    exercise = CarrierApproachExercise(_profile(), started_at=0.0)
    assert (
        exercise.update(
            _ownship(distance_m=1000.0, error_m=-20.0, timestamp=0.0),
            _carrier(0.0),
            now=0.0,
        )
        == ()
    )
    feedback = exercise.update(
        _ownship(distance_m=900.0, error_m=-25.0, timestamp=1.1),
        _carrier(1.1),
        now=1.1,
    )
    assert [item.message for item in feedback] == ["You're low."]

    assert (
        exercise.update(
            _ownship(distance_m=800.0, error_m=-8.0, timestamp=2.0),
            _carrier(2.0),
            now=2.0,
        )
        == ()
    )


def test_carrier_approach_debrief_contains_deterministic_geometry() -> None:
    exercise = CarrierApproachExercise(_profile(), started_at=0.0)
    exercise.update(
        _ownship(distance_m=1000.0, error_m=-20.0, timestamp=0.0),
        _carrier(0.0),
        now=0.0,
    )
    exercise.update(
        _ownship(distance_m=800.0, error_m=-10.0, timestamp=2.0), _carrier(2.0), now=2.0
    )

    debrief = exercise.stop(now=2.0)

    assert debrief["mean_glidepath_error_m"] == pytest.approx(-15.0)
    assert debrief["max_low_m"] == pytest.approx(-20.0)
    assert debrief["mean_lineup_error_m"] == pytest.approx(0.0)
