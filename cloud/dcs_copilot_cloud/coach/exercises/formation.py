"""Configurable deterministic echelon-formation coaching."""

from __future__ import annotations

import math
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


class FormationZone(StrEnum):
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    OUTSIDE = "OUTSIDE"


@dataclass(frozen=True, slots=True)
class FormationTarget:
    forward_m: float
    right_m: float
    up_m: float


@dataclass(frozen=True, slots=True)
class FormationTolerance:
    good_m: float
    acceptable_m: float

    def __post_init__(self) -> None:
        if self.good_m <= 0 or self.acceptable_m < self.good_m:
            raise ValueError("formation tolerances must be positive and ordered")


@dataclass(frozen=True, slots=True)
class FormationProfile:
    aircraft: str
    training_profile: str
    target: FormationTarget
    tolerance: FormationTolerance
    outside_hold_seconds: float = 1.5
    good_hold_seconds: float = 2.0
    speech_cooldown_seconds: float = 5.0
    closure_warning_mps: float = 3.0


@dataclass(frozen=True, slots=True)
class FormationSample:
    timestamp: float
    forward_error_m: float
    lateral_error_m: float
    vertical_error_m: float
    closure_mps: float | None
    zone: FormationZone
    relative: RelativeObservation

    @property
    def position_error_m(self) -> float:
        return math.sqrt(
            self.forward_error_m**2 + self.lateral_error_m**2 + self.vertical_error_m**2
        )


def default_echelon_profile(exercise: ExerciseId) -> FormationProfile:
    if exercise not in {ExerciseId.LEFT_ECHELON, ExerciseId.RIGHT_ECHELON}:
        raise ValueError("an echelon profile requires an echelon exercise")
    lateral = -18.0 if exercise is ExerciseId.LEFT_ECHELON else 18.0
    return FormationProfile(
        aircraft="GENERIC",
        training_profile="default",
        target=FormationTarget(forward_m=-22.0, right_m=lateral, up_m=0.0),
        tolerance=FormationTolerance(good_m=3.0, acceptable_m=7.5),
    )


class FormationExercise(CoachExercise):
    reference_type = ReferenceObjectType.LEAD_AIRCRAFT

    def __init__(
        self,
        profile: FormationProfile,
        *,
        started_at: float,
        exercise_id: ExerciseId = ExerciseId.LEFT_ECHELON,
        stale_after: float = 1.0,
    ) -> None:
        super().__init__(started_at=started_at)
        self.id = exercise_id
        self.profile = profile
        self.stale_after = stale_after
        self.samples: deque[FormationSample] = deque(maxlen=MAX_EXERCISE_SAMPLES)
        self.last_sample: FormationSample | None = None
        self._zone_seconds = {zone: 0.0 for zone in FormationZone}
        self._condition: str | None = None
        self._condition_since = started_at
        self._last_spoken_at = float("-inf")
        self._closure_overshoots = 0
        self._closure_warning_active = False

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
            self.reason = "Waiting for current ownship and lead observations."
            return ()
        self.state = ExerciseState.ACTIVE
        self.reason = None
        local = relative_position(reference.pose, pose.position)
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
            relative_heading_deg=_angle_delta(pose.heading_deg, reference.heading_deg),
        )
        errors = (
            local.forward_m - self.profile.target.forward_m,
            local.right_m - self.profile.target.right_m,
            local.up_m - self.profile.target.up_m,
        )
        zone = self._zone(errors)
        if self.last_sample is not None:
            elapsed = max(0.0, now - self.last_sample.timestamp)
            self._zone_seconds[self.last_sample.zone] += elapsed
        sample = FormationSample(now, *errors, closure, zone, relative)
        self.samples.append(sample)
        self.last_sample = sample
        return self._feedback_for(sample, now=now)

    def stop(self, *, now: float, reason: str | None = None) -> dict[str, Any]:
        super().stop(now=now, reason=reason)
        duration = max(0.0, now - self.started_at)
        if not self.samples:
            return {
                "exercise": self.id.value,
                "duration_seconds": duration,
                "samples": 0,
                "reason": reason,
            }
        count = len(self.samples)
        mean_forward = sum(item.forward_error_m for item in self.samples) / count
        mean_lateral = sum(item.lateral_error_m for item in self.samples) / count
        mean_vertical = sum(item.vertical_error_m for item in self.samples) / count
        axes = {
            "fore_aft": abs(mean_forward),
            "lateral": abs(mean_lateral),
            "vertical": abs(mean_vertical),
        }
        rms = math.sqrt(sum(item.position_error_m**2 for item in self.samples) / count)
        result: dict[str, Any] = {
            "exercise": self.id.value,
            "profile": self.profile.training_profile,
            "aircraft": self.profile.aircraft,
            "duration_seconds": duration,
            "samples": count,
            "time_good_seconds": self._zone_seconds[FormationZone.GOOD],
            "time_acceptable_seconds": self._zone_seconds[FormationZone.ACCEPTABLE],
            "time_outside_seconds": self._zone_seconds[FormationZone.OUTSIDE],
            "mean_forward_error_m": mean_forward,
            "mean_lateral_error_m": mean_lateral,
            "mean_vertical_error_m": mean_vertical,
            "rms_position_error_m": rms,
            "max_position_error_m": max(item.position_error_m for item in self.samples),
            "dominant_error_axis": max(axes, key=lambda name: axes[name]),
            "closure_overshoots": self._closure_overshoots,
        }
        if duration > 0:
            result["time_good_percent"] = (
                self._zone_seconds[FormationZone.GOOD] / duration * 100.0
            )
            result["time_acceptable_percent"] = (
                self._zone_seconds[FormationZone.ACCEPTABLE] / duration * 100.0
            )
            result["time_outside_percent"] = (
                self._zone_seconds[FormationZone.OUTSIDE] / duration * 100.0
            )
        if reason is not None:
            result["reason"] = reason
        return result

    def _zone(self, errors: tuple[float, float, float]) -> FormationZone:
        largest = max(abs(value) for value in errors)
        if largest <= self.profile.tolerance.good_m:
            return FormationZone.GOOD
        if largest <= self.profile.tolerance.acceptable_m:
            return FormationZone.ACCEPTABLE
        return FormationZone.OUTSIDE

    def _feedback_for(
        self, sample: FormationSample, *, now: float
    ) -> tuple[CoachFeedback, ...]:
        closure_warning = (
            sample.closure_mps is not None
            and abs(sample.closure_mps) > self.profile.closure_warning_mps
        )
        if closure_warning and not self._closure_warning_active:
            self._closure_overshoots += 1
        self._closure_warning_active = closure_warning
        if closure_warning:
            condition = "closure"
            message = "Watch your closure."
        elif sample.zone is FormationZone.GOOD:
            condition = "good"
            message = "Good position. Hold that."
        elif sample.zone is FormationZone.OUTSIDE:
            condition, message = _direction_feedback(sample)
        else:
            condition = "acceptable"
            message = ""
        if condition != self._condition:
            self._condition = condition
            self._condition_since = now
            return ()
        hold = (
            self.profile.good_hold_seconds
            if condition == "good"
            else self.profile.outside_hold_seconds
        )
        if condition == "acceptable" or not message:
            return ()
        if now - self._condition_since < hold:
            return ()
        if now - self._last_spoken_at < self.profile.speech_cooldown_seconds:
            return ()
        self._last_spoken_at = now
        return (
            CoachFeedback(
                code=f"FORMATION_{condition.upper()}",
                message=message,
                timestamp=now,
                data={
                    "forward_error_m": sample.forward_error_m,
                    "lateral_error_m": sample.lateral_error_m,
                    "vertical_error_m": sample.vertical_error_m,
                    "closure_mps": sample.closure_mps,
                    "zone": sample.zone.value,
                },
            ),
        )


def _direction_feedback(sample: FormationSample) -> tuple[str, str]:
    errors = {
        "forward": sample.forward_error_m,
        "lateral": sample.lateral_error_m,
        "vertical": sample.vertical_error_m,
    }
    axis = max(errors, key=lambda name: abs(errors[name]))
    value = errors[axis]
    if axis == "forward":
        return (
            "forward",
            "Ease back a little." if value > 0 else "Come forward a little.",
        )
    if axis == "lateral":
        return (
            "lateral",
            "Move left a little." if value > 0 else "Move right a little.",
        )
    return (
        "vertical",
        "You're a little high." if value > 0 else "You're a little low.",
    )


def _angle_delta(target_deg: float, reference_deg: float) -> float:
    return (target_deg - reference_deg + 180.0) % 360.0 - 180.0
