"""Carrier-relative glidepath and lineup coaching with deterministic trends."""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..models import (
    ObservationQuality,
    OwnshipState,
    ReferenceObject,
    ReferenceObjectType,
    RelativeObservation,
)
from ..spatial import closure_rate, distance, relative_position
from .base import (
    MAX_EXERCISE_SAMPLES,
    CoachExercise,
    CoachFeedback,
    ExerciseId,
    ExerciseState,
)


class GlidepathState(StrEnum):
    ON_GLIDEPATH = "ON_GLIDEPATH"
    SLIGHTLY_LOW = "SLIGHTLY_LOW"
    LOW = "LOW"
    RECOVERING = "RECOVERING"
    DIVERGING_LOW = "DIVERGING_LOW"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class CarrierApproachProfile:
    name: str
    glidepath_deg: float
    aimpoint_offset_m: float
    acceptable_vertical_error_m: float
    acceptable_lineup_error_m: float
    low_error_m: float
    trend_window_seconds: float = 5.0
    feedback_hold_seconds: float = 1.0
    speech_cooldown_seconds: float = 4.0

    def __post_init__(self) -> None:
        if not 0.1 < self.glidepath_deg < 10.0:
            raise ValueError("carrier glidepath must be between 0.1 and 10 degrees")
        if self.acceptable_vertical_error_m <= 0 or self.acceptable_lineup_error_m <= 0:
            raise ValueError("carrier approach tolerances must be positive")
        if self.low_error_m < self.acceptable_vertical_error_m:
            raise ValueError("low threshold must exceed acceptable vertical error")


@dataclass(frozen=True, slots=True)
class CarrierApproachSample:
    timestamp: float
    along_track_m: float
    cross_track_error_m: float
    relative_altitude_m: float
    desired_altitude_m: float
    glidepath_error_m: float
    glidepath_trend_mps: float | None
    glidepath_state: GlidepathState
    closure_mps: float | None
    relative: RelativeObservation
    indicated_airspeed_kt: float | None = None
    aoa_deg: float | None = None


def default_hornet_carrier_profile() -> CarrierApproachProfile:
    """Configurable initial assumption for a Hornet carrier recovery."""

    return CarrierApproachProfile(
        name="hornet_default",
        glidepath_deg=3.5,
        aimpoint_offset_m=0.0,
        acceptable_vertical_error_m=5.0,
        acceptable_lineup_error_m=8.0,
        low_error_m=15.0,
    )


class CarrierApproachExercise(CoachExercise):
    id = ExerciseId.CARRIER_APPROACH
    reference_type = ReferenceObjectType.CARRIER

    def __init__(
        self,
        profile: CarrierApproachProfile,
        *,
        started_at: float,
        stale_after: float = 1.0,
    ) -> None:
        super().__init__(started_at=started_at)
        self.profile = profile
        self.stale_after = stale_after
        self.samples: deque[CarrierApproachSample] = deque(maxlen=MAX_EXERCISE_SAMPLES)
        self.last_sample: CarrierApproachSample | None = None
        self._condition: str | None = None
        self._condition_since = started_at
        self._last_spoken_at = float("-inf")
        self._low_spoken = False

    def update(
        self,
        ownship: OwnshipState,
        reference: ReferenceObject,
        *,
        now: float,
    ) -> tuple[CoachFeedback, ...]:
        pose = ownship.pose(now, stale_after=self.stale_after)
        if (
            pose is None
            or reference.quality_at(now, stale_after=self.stale_after)
            is ObservationQuality.STALE
        ):
            self.state = ExerciseState.PAUSED
            self.reason = "Waiting for current ownship and carrier observations."
            return ()
        self.state = ExerciseState.ACTIVE
        self.reason = None
        local = relative_position(reference.pose, pose.position)
        along_track = max(0.0, -local.forward_m + self.profile.aimpoint_offset_m)
        desired_altitude = (
            math.tan(math.radians(self.profile.glidepath_deg)) * along_track
        )
        glidepath_error = local.up_m - desired_altitude
        previous = self._trend_reference(now)
        trend = None
        if previous is not None and now > previous.timestamp:
            trend = (glidepath_error - previous.glidepath_error_m) / (
                now - previous.timestamp
            )
        state = self._classify(glidepath_error, trend)
        closure: float | None = None
        if ownship.velocity.usable(now, stale_after=self.stale_after):
            assert ownship.velocity.value is not None
            if reference.velocity is not None:
                closure = closure_rate(
                    reference_position=reference.position,
                    reference_velocity=reference.velocity,
                    target_position=pose.position,
                    target_velocity=ownship.velocity.value,
                )
        range_m = distance(reference.position, pose.position)
        bearing = (
            math.degrees(math.atan2(local.right_m, local.forward_m))
            if range_m
            else None
        )
        relative = RelativeObservation.from_local(
            local,
            range_m=range_m,
            closure_mps=closure,
            bearing_deg=bearing,
            timestamp=now,
            quality=ObservationQuality.GOOD,
        )
        sample = CarrierApproachSample(
            now,
            along_track,
            local.right_m,
            local.up_m,
            desired_altitude,
            glidepath_error,
            trend,
            state,
            closure,
            relative,
            (
                ownship.indicated_airspeed_kt.value
                if ownship.indicated_airspeed_kt.usable(
                    now, stale_after=self.stale_after
                )
                else None
            ),
            (
                ownship.aoa_deg.value
                if ownship.aoa_deg.usable(now, stale_after=self.stale_after)
                else None
            ),
        )
        self.samples.append(sample)
        self.last_sample = sample
        return self._feedback_for(sample, now=now)

    def stop(self, *, now: float, reason: str | None = None) -> dict[str, Any]:
        super().stop(now=now, reason=reason)
        result: dict[str, Any] = {
            "exercise": self.id.value,
            "profile": self.profile.name,
            "duration_seconds": max(0.0, now - self.started_at),
            "samples": len(self.samples),
        }
        if self.samples:
            airspeeds = [
                sample.indicated_airspeed_kt
                for sample in self.samples
                if sample.indicated_airspeed_kt is not None
            ]
            aoa_values = [
                sample.aoa_deg for sample in self.samples if sample.aoa_deg is not None
            ]
            result.update(
                mean_glidepath_error_m=sum(
                    sample.glidepath_error_m for sample in self.samples
                )
                / len(self.samples),
                max_low_m=min(sample.glidepath_error_m for sample in self.samples),
                max_high_m=max(sample.glidepath_error_m for sample in self.samples),
                mean_lineup_error_m=sum(
                    sample.cross_track_error_m for sample in self.samples
                )
                / len(self.samples),
                max_lineup_error_m=max(
                    abs(sample.cross_track_error_m) for sample in self.samples
                ),
                airspeed_standard_deviation_kt=(
                    statistics.pstdev(airspeeds)
                    if len(airspeeds) > 1
                    else 0.0
                    if airspeeds
                    else None
                ),
                aoa_standard_deviation_deg=(
                    statistics.pstdev(aoa_values)
                    if len(aoa_values) > 1
                    else 0.0
                    if aoa_values
                    else None
                ),
            )
        if reason is not None:
            result["reason"] = reason
        return result

    def _trend_reference(self, now: float) -> CarrierApproachSample | None:
        candidates = [
            sample
            for sample in self.samples
            if now - sample.timestamp <= self.profile.trend_window_seconds
        ]
        return candidates[0] if candidates else None

    def _classify(self, error: float, trend: float | None) -> GlidepathState:
        tolerance = self.profile.acceptable_vertical_error_m
        if abs(error) <= tolerance:
            return GlidepathState.ON_GLIDEPATH
        if error > tolerance:
            return GlidepathState.HIGH
        if trend is not None and trend > 0.5:
            return GlidepathState.RECOVERING
        if error <= -self.profile.low_error_m:
            if trend is not None and trend < -0.5:
                return GlidepathState.DIVERGING_LOW
            return GlidepathState.LOW
        return GlidepathState.SLIGHTLY_LOW

    def _feedback_for(
        self, sample: CarrierApproachSample, *, now: float
    ) -> tuple[CoachFeedback, ...]:
        if sample.glidepath_state in {
            GlidepathState.LOW,
            GlidepathState.DIVERGING_LOW,
            GlidepathState.SLIGHTLY_LOW,
        }:
            condition = "low"
        elif abs(sample.cross_track_error_m) > self.profile.acceptable_lineup_error_m:
            condition = "lineup"
        else:
            condition = sample.glidepath_state.value.lower()
        if condition != self._condition:
            self._condition = condition
            self._condition_since = now
            return ()
        if condition not in {"low", "lineup"}:
            return ()
        if now - self._condition_since < self.profile.feedback_hold_seconds:
            return ()
        if now - self._last_spoken_at < self.profile.speech_cooldown_seconds:
            return ()
        if condition == "lineup":
            message = (
                "Ease left for lineup."
                if sample.cross_track_error_m > 0
                else "Ease right for lineup."
            )
        elif (
            self._low_spoken and sample.glidepath_state is GlidepathState.DIVERGING_LOW
        ):
            message = "Still trending low."
        elif sample.glidepath_state is GlidepathState.SLIGHTLY_LOW:
            message = "You're slightly low."
        else:
            message = "You're low."
        self._last_spoken_at = now
        self._low_spoken = condition == "low"
        return (
            CoachFeedback(
                code=f"CARRIER_{condition.upper()}",
                message=message,
                timestamp=now,
                data={
                    "glidepath_error_m": sample.glidepath_error_m,
                    "glidepath_trend_mps": sample.glidepath_trend_mps,
                    "lineup_error_m": sample.cross_track_error_m,
                    "state": sample.glidepath_state.value,
                },
            ),
        )
