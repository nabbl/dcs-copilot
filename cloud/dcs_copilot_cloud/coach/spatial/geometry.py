"""Source-independent spatial measurements."""

from __future__ import annotations

from .transforms import LocalVector
from .vectors import Vec3


def distance(first: Vec3, second: Vec3) -> float:
    return (second - first).magnitude


def closure_rate(
    *,
    reference_position: Vec3,
    reference_velocity: Vec3,
    target_position: Vec3,
    target_velocity: Vec3,
) -> float | None:
    displacement = target_position - reference_position
    separation = displacement.magnitude
    if separation == 0.0:
        return None
    relative_velocity = target_velocity - reference_velocity
    range_rate = (
        displacement.x * relative_velocity.x
        + displacement.y * relative_velocity.y
        + displacement.z * relative_velocity.z
    ) / separation
    return -range_rate


def cross_track_error(
    observation: LocalVector,
    *,
    target_right_m: float = 0.0,
) -> float:
    return observation.right_m - target_right_m


def vertical_error(
    observation: LocalVector,
    *,
    target_up_m: float = 0.0,
) -> float:
    return observation.up_m - target_up_m
