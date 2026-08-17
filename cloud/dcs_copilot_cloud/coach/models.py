"""Normalized sourced observations consumed by deterministic Coach exercises."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Generic, TypeVar

from .spatial import LocalVector, Pose, Vec3

T = TypeVar("T")


class TelemetrySource(StrEnum):
    DCS_EXPORT = "DCS_EXPORT"
    DCS_BIOS = "DCS_BIOS"
    REPLAY = "REPLAY"
    TACVIEW = "TACVIEW"


class ObservationQuality(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ReferenceObjectType(StrEnum):
    LEAD_AIRCRAFT = "LEAD_AIRCRAFT"
    CARRIER = "CARRIER"


@dataclass(frozen=True, slots=True)
class ObservedValue(Generic[T]):
    value: T | None = None
    source: TelemetrySource | None = None
    timestamp: float | None = None
    available: bool = False
    quality: ObservationQuality = ObservationQuality.UNAVAILABLE

    @classmethod
    def observed(
        cls,
        value: T,
        *,
        source: TelemetrySource,
        timestamp: float,
        quality: ObservationQuality = ObservationQuality.GOOD,
    ) -> ObservedValue[T]:
        return cls(value, source, timestamp, True, quality)

    def quality_at(self, now: float, *, stale_after: float) -> ObservationQuality:
        if not self.available or self.value is None or self.timestamp is None:
            return ObservationQuality.UNAVAILABLE
        if now - self.timestamp > stale_after:
            return ObservationQuality.STALE
        return self.quality

    def usable(self, now: float, *, stale_after: float) -> bool:
        return self.quality_at(now, stale_after=stale_after) in {
            ObservationQuality.GOOD,
            ObservationQuality.DEGRADED,
        }


def unavailable_value() -> ObservedValue[object]:
    return ObservedValue()


@dataclass(frozen=True, slots=True)
class OwnshipState:
    position: ObservedValue[Vec3] = field(default_factory=ObservedValue)
    velocity: ObservedValue[Vec3] = field(default_factory=ObservedValue)
    heading_deg: ObservedValue[float] = field(default_factory=ObservedValue)
    pitch_deg: ObservedValue[float] = field(default_factory=ObservedValue)
    roll_deg: ObservedValue[float] = field(default_factory=ObservedValue)
    altitude_msl_ft: ObservedValue[float] = field(default_factory=ObservedValue)
    altitude_agl_ft: ObservedValue[float] = field(default_factory=ObservedValue)
    indicated_airspeed_kt: ObservedValue[float] = field(default_factory=ObservedValue)
    vertical_speed_fpm: ObservedValue[float] = field(default_factory=ObservedValue)
    aoa_deg: ObservedValue[float] = field(default_factory=ObservedValue)
    g_force: ObservedValue[float] = field(default_factory=ObservedValue)
    gear_down: ObservedValue[bool] = field(default_factory=ObservedValue)
    timestamp: float = 0.0

    def pose(self, now: float, *, stale_after: float) -> Pose | None:
        required = (self.position, self.heading_deg)
        if not all(value.usable(now, stale_after=stale_after) for value in required):
            return None
        assert self.position.value is not None
        assert self.heading_deg.value is not None
        pitch = (
            self.pitch_deg.value
            if self.pitch_deg.usable(now, stale_after=stale_after)
            else 0.0
        )
        roll = (
            self.roll_deg.value
            if self.roll_deg.usable(now, stale_after=stale_after)
            else 0.0
        )
        return Pose(
            self.position.value, self.heading_deg.value, pitch or 0.0, roll or 0.0
        )


@dataclass(frozen=True, slots=True)
class ReferenceObject:
    object_id: str
    object_type: ReferenceObjectType
    position: Vec3
    heading_deg: float
    timestamp: float
    source: TelemetrySource
    velocity: Vec3 | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    name: str | None = None
    quality: ObservationQuality = ObservationQuality.GOOD

    @property
    def pose(self) -> Pose:
        return Pose(
            self.position,
            self.heading_deg,
            self.pitch_deg or 0.0,
            self.roll_deg or 0.0,
        )

    def quality_at(self, now: float, *, stale_after: float) -> ObservationQuality:
        if now - self.timestamp > stale_after:
            return ObservationQuality.STALE
        return self.quality

    def with_quality(self, quality: ObservationQuality) -> ReferenceObject:
        return replace(self, quality=quality)


@dataclass(frozen=True, slots=True)
class RelativeObservation:
    range_m: float
    forward_m: float
    right_m: float
    up_m: float
    closure_mps: float | None
    bearing_deg: float | None
    timestamp: float
    quality: ObservationQuality
    relative_heading_deg: float | None = None
    relative_speed_mps: float | None = None

    @classmethod
    def from_local(
        cls,
        local: LocalVector,
        *,
        range_m: float,
        closure_mps: float | None,
        bearing_deg: float | None,
        timestamp: float,
        quality: ObservationQuality,
        relative_heading_deg: float | None = None,
        relative_speed_mps: float | None = None,
    ) -> RelativeObservation:
        return cls(
            range_m,
            local.forward_m,
            local.right_m,
            local.up_m,
            closure_mps,
            bearing_deg,
            timestamp,
            quality,
            relative_heading_deg,
            relative_speed_mps,
        )
