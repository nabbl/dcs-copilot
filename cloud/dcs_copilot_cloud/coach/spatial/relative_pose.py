"""Relative position and motion derived from the common spatial transform."""

from __future__ import annotations

from .transforms import LocalVector, Pose, world_to_local
from .vectors import Vec3


def relative_position(reference_pose: Pose, target_position: Vec3) -> LocalVector:
    return world_to_local(reference_pose, target_position)


def relative_velocity(
    reference_pose: Pose,
    reference_velocity: Vec3,
    target_velocity: Vec3,
) -> LocalVector:
    delta = target_velocity - reference_velocity
    orientation = Pose(
        position=Vec3(0.0, 0.0, 0.0),
        heading_deg=reference_pose.heading_deg,
        pitch_deg=reference_pose.pitch_deg,
        roll_deg=reference_pose.roll_deg,
    )
    return world_to_local(orientation, delta)
