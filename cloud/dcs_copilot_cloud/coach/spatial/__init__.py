"""Dependency-free spatial primitives shared by all Coach exercises."""

from .geometry import closure_rate, cross_track_error, distance, vertical_error
from .relative_pose import relative_position, relative_velocity
from .transforms import LocalVector, Pose, world_to_local
from .vectors import Vec3

__all__ = [
    "LocalVector",
    "Pose",
    "Vec3",
    "closure_rate",
    "cross_track_error",
    "distance",
    "relative_position",
    "relative_velocity",
    "vertical_error",
    "world_to_local",
]
