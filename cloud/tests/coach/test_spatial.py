from __future__ import annotations

import pytest
from dcs_copilot_cloud.coach.spatial.geometry import (
    closure_rate,
    cross_track_error,
    distance,
    vertical_error,
)
from dcs_copilot_cloud.coach.spatial.relative_pose import (
    relative_position,
    relative_velocity,
)
from dcs_copilot_cloud.coach.spatial.transforms import LocalVector, Pose, world_to_local
from dcs_copilot_cloud.coach.spatial.vectors import Vec3


def test_distance_uses_all_three_dcs_axes() -> None:
    origin = Vec3(10.0, 20.0, 30.0)
    target = Vec3(13.0, 24.0, 42.0)

    assert distance(origin, target) == pytest.approx(13.0)


def test_world_to_local_rotates_position_into_reference_heading() -> None:
    reference = Pose(position=Vec3(100.0, 20.0, 200.0), heading_deg=90.0)

    observation = world_to_local(reference, Vec3(90.0, 25.0, 230.0))

    assert observation.forward_m == pytest.approx(30.0)
    assert observation.right_m == pytest.approx(10.0)
    assert observation.up_m == pytest.approx(5.0)


def test_world_to_local_honors_reference_pitch_and_roll() -> None:
    pitched = Pose(
        position=Vec3(0.0, 0.0, 0.0),
        heading_deg=0.0,
        pitch_deg=90.0,
    )
    rolled = Pose(
        position=Vec3(0.0, 0.0, 0.0),
        heading_deg=0.0,
        roll_deg=90.0,
    )

    nose_up = world_to_local(pitched, Vec3(0.0, 10.0, 0.0))
    right_wing_down = world_to_local(rolled, Vec3(0.0, -10.0, 0.0))

    assert nose_up.forward_m == pytest.approx(10.0)
    assert nose_up.right_m == pytest.approx(0.0, abs=1e-12)
    assert nose_up.up_m == pytest.approx(0.0, abs=1e-12)
    assert right_wing_down.right_m == pytest.approx(10.0)
    assert right_wing_down.up_m == pytest.approx(0.0, abs=1e-12)


def test_relative_pose_uses_the_same_reference_frame_for_position_and_velocity() -> (
    None
):
    reference = Pose(position=Vec3(100.0, 0.0, 200.0), heading_deg=90.0)

    position = relative_position(reference, Vec3(90.0, 5.0, 230.0))
    velocity = relative_velocity(
        reference,
        reference_velocity=Vec3(5.0, 0.0, 20.0),
        target_velocity=Vec3(2.0, 1.0, 30.0),
    )

    assert position.forward_m == pytest.approx(30.0)
    assert position.right_m == pytest.approx(10.0)
    assert position.up_m == pytest.approx(5.0)
    assert velocity.forward_m == pytest.approx(10.0)
    assert velocity.right_m == pytest.approx(3.0)
    assert velocity.up_m == pytest.approx(1.0)


def test_closure_is_positive_when_range_is_decreasing() -> None:
    closure = closure_rate(
        reference_position=Vec3(0.0, 0.0, 0.0),
        reference_velocity=Vec3(10.0, 0.0, 0.0),
        target_position=Vec3(100.0, 0.0, 0.0),
        target_velocity=Vec3(5.0, 0.0, 0.0),
    )

    assert closure == pytest.approx(5.0)
    assert (
        closure_rate(
            reference_position=Vec3(1.0, 2.0, 3.0),
            reference_velocity=Vec3(0.0, 0.0, 0.0),
            target_position=Vec3(1.0, 2.0, 3.0),
            target_velocity=Vec3(0.0, 0.0, 0.0),
        )
        is None
    )


def test_cross_track_and_vertical_errors_are_relative_to_configured_targets() -> None:
    observation = LocalVector(forward_m=-30.0, right_m=-12.0, up_m=4.0)

    assert cross_track_error(observation, target_right_m=-10.0) == pytest.approx(-2.0)
    assert vertical_error(observation, target_up_m=6.0) == pytest.approx(-2.0)
