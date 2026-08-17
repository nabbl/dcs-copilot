"""Transforms from DCS world coordinates into a reference-local frame."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .vectors import Vec3


@dataclass(frozen=True, slots=True)
class Pose:
    position: Vec3
    heading_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class LocalVector:
    forward_m: float
    right_m: float
    up_m: float


def world_to_local(reference_pose: Pose, target_position: Vec3) -> LocalVector:
    offset = target_position - reference_pose.position
    heading = math.radians(reference_pose.heading_deg)
    pitch = math.radians(reference_pose.pitch_deg)
    roll = math.radians(reference_pose.roll_deg)
    heading_cosine = math.cos(heading)
    heading_sine = math.sin(heading)
    pitch_cosine = math.cos(pitch)
    pitch_sine = math.sin(pitch)
    roll_cosine = math.cos(roll)
    roll_sine = math.sin(roll)

    forward = Vec3(
        pitch_cosine * heading_cosine,
        pitch_sine,
        pitch_cosine * heading_sine,
    )
    level_right = Vec3(-heading_sine, 0.0, heading_cosine)
    unrolled_up = Vec3(
        -pitch_sine * heading_cosine,
        pitch_cosine,
        -pitch_sine * heading_sine,
    )
    right = Vec3(
        level_right.x * roll_cosine - unrolled_up.x * roll_sine,
        level_right.y * roll_cosine - unrolled_up.y * roll_sine,
        level_right.z * roll_cosine - unrolled_up.z * roll_sine,
    )
    up = Vec3(
        level_right.x * roll_sine + unrolled_up.x * roll_cosine,
        level_right.y * roll_sine + unrolled_up.y * roll_cosine,
        level_right.z * roll_sine + unrolled_up.z * roll_cosine,
    )
    return LocalVector(
        forward_m=_dot(offset, forward),
        right_m=_dot(offset, right),
        up_m=_dot(offset, up),
    )


def _dot(first: Vec3, second: Vec3) -> float:
    return first.x * second.x + first.y * second.y + first.z * second.z
