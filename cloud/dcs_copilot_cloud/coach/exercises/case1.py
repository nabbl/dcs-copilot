"""Deterministic CASE I phase segmentation in the moving carrier frame."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..models import (
    ObservationQuality,
    OwnshipState,
    ReferenceObject,
    ReferenceObjectType,
)
from ..spatial import relative_position
from .base import (
    MAX_EXERCISE_SAMPLES,
    CoachExercise,
    CoachFeedback,
    ExerciseId,
    ExerciseState,
)

METERS_PER_NM = 1852.0
FEET_PER_METER = 3.28084


class Case1Phase(StrEnum):
    UNKNOWN = "UNKNOWN"
    INITIAL = "INITIAL"
    BREAK = "BREAK"
    DOWNWIND = "DOWNWIND"
    ABEAM = "ABEAM"
    ONE_EIGHTY = "180"
    NINETY = "90"
    GROOVE = "GROOVE"
    TRAP_OR_BOLTER = "TRAP_OR_BOLTER"


@dataclass(frozen=True, slots=True)
class Case1Profile:
    name: str
    target_initial_altitude_ft: float = 800.0
    target_initial_airspeed_kt: float = 350.0
    target_downwind_altitude_ft: float = 600.0
    target_downwind_abeam_nm: float = 1.25
    glidepath_deg: float = 3.5
    groove_lineup_tolerance_m: float = 50.0
    initial_min_distance_m: float = 500.0
    abeam_forward_window_m: float = 300.0


@dataclass(frozen=True, slots=True)
class Case1Sample:
    timestamp: float
    phase: Case1Phase
    forward_m: float
    right_m: float
    altitude_ft: float | None
    heading_relative_deg: float
    airspeed_kt: float | None
    roll_deg: float | None
    turn_rate_dps: float | None = None
    g_force: float | None = None
    glidepath_error_ft: float | None = None
    lineup_error_m: float | None = None


@dataclass(slots=True)
class Case1Segment:
    phase: Case1Phase
    started_at: float
    entry_state: Case1Sample
    ended_at: float | None = None
    exit_state: Case1Sample | None = None
    samples: deque[Case1Sample] = field(
        default_factory=lambda: deque(maxlen=MAX_EXERCISE_SAMPLES)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "start_timestamp": self.started_at,
            "end_timestamp": self.ended_at,
            "duration_seconds": (
                max(0.0, self.ended_at - self.started_at)
                if self.ended_at is not None
                else None
            ),
            "entry": _sample_state(self.entry_state),
            "exit": _sample_state(self.exit_state) if self.exit_state else None,
            "samples": len(self.samples),
        }


def default_case1_profile() -> Case1Profile:
    return Case1Profile(name="hornet_default")


class Case1Exercise(CoachExercise):
    id = ExerciseId.CASE1_PATTERN
    reference_type = ReferenceObjectType.CARRIER

    def __init__(
        self,
        profile: Case1Profile,
        *,
        started_at: float,
        stale_after: float = 1.0,
    ) -> None:
        super().__init__(started_at=started_at)
        self.profile = profile
        self.stale_after = stale_after
        self.phase = Case1Phase.UNKNOWN
        self.samples: deque[Case1Sample] = deque(maxlen=MAX_EXERCISE_SAMPLES)
        self.segments: list[Case1Segment] = []

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
        relative_heading = _angle_delta(pose.heading_deg, reference.heading_deg)
        altitude_ft = _usable_value(ownship.altitude_msl_ft, now, self.stale_after)
        if altitude_ft is None:
            altitude_ft = local.up_m * FEET_PER_METER
        airspeed = _usable_value(ownship.indicated_airspeed_kt, now, self.stale_after)
        roll = _usable_value(ownship.roll_deg, now, self.stale_after)
        gear_down = _usable_value(ownship.gear_down, now, self.stale_after)
        g_force = _usable_value(ownship.g_force, now, self.stale_after)
        turn_rate = None
        if self.samples and now > self.samples[-1].timestamp:
            turn_rate = _angle_delta(
                relative_heading, self.samples[-1].heading_relative_deg
            ) / (now - self.samples[-1].timestamp)
        phase = self._next_phase(
            forward_m=local.forward_m,
            right_m=local.right_m,
            altitude_ft=altitude_ft,
            relative_heading_deg=relative_heading,
            roll_deg=roll,
            turn_rate_dps=turn_rate,
            gear_down=gear_down,
        )
        glidepath_error: float | None = None
        lineup_error: float | None = None
        if phase is Case1Phase.GROOVE:
            distance_m = max(0.0, -local.forward_m)
            desired_ft = (
                math.tan(math.radians(self.profile.glidepath_deg))
                * distance_m
                * FEET_PER_METER
            )
            glidepath_error = altitude_ft - desired_ft
            lineup_error = local.right_m
        sample = Case1Sample(
            now,
            phase,
            local.forward_m,
            local.right_m,
            altitude_ft,
            relative_heading,
            airspeed,
            roll,
            turn_rate,
            g_force,
            glidepath_error,
            lineup_error,
        )
        self._record(sample)
        self.phase = phase
        self.samples.append(sample)
        return ()

    def stop(self, *, now: float, reason: str | None = None) -> dict[str, Any]:
        super().stop(now=now, reason=reason)
        if self.segments and self.segments[-1].ended_at is None:
            self.segments[-1].ended_at = now
            self.segments[-1].exit_state = self.segments[-1].samples[-1]
        downwind = [
            sample for sample in self.samples if sample.phase is Case1Phase.DOWNWIND
        ]
        at_180 = next(
            (
                sample
                for sample in self.samples
                if sample.phase is Case1Phase.ONE_EIGHTY
            ),
            None,
        )
        groove = [
            sample for sample in self.samples if sample.phase is Case1Phase.GROOVE
        ]
        break_samples = [
            sample for sample in self.samples if sample.phase is Case1Phase.BREAK
        ]
        result: dict[str, Any] = {
            "exercise": self.id.value,
            "profile": self.profile.name,
            "duration_seconds": max(0.0, now - self.started_at),
            "segments": [segment.to_dict() for segment in self.segments],
            "downwind": {
                "mean_abeam_nm": _mean(
                    abs(sample.right_m) / METERS_PER_NM for sample in downwind
                ),
                "target_abeam_nm": self.profile.target_downwind_abeam_nm,
                "mean_altitude_ft": _mean(sample.altitude_ft for sample in downwind),
            },
            "at_180": {
                "altitude_ft": at_180.altitude_ft if at_180 else None,
                "distance_abeam_nm": (
                    abs(at_180.right_m) / METERS_PER_NM if at_180 else None
                ),
            },
            "break": {
                "position_forward_m": break_samples[0].forward_m
                if break_samples
                else None,
                "altitude_ft": break_samples[0].altitude_ft if break_samples else None,
                "max_turn_rate_dps": max(
                    (
                        abs(sample.turn_rate_dps)
                        for sample in break_samples
                        if sample.turn_rate_dps is not None
                    ),
                    default=None,
                ),
                "max_g": max(
                    (
                        sample.g_force
                        for sample in break_samples
                        if sample.g_force is not None
                    ),
                    default=None,
                ),
            },
            "groove": {
                "mean_glidepath_error_ft": _mean(
                    sample.glidepath_error_ft for sample in groove
                ),
                "max_low_ft": min(
                    (
                        sample.glidepath_error_ft
                        for sample in groove
                        if sample.glidepath_error_ft is not None
                    ),
                    default=None,
                ),
                "mean_lineup_error_m": _mean(
                    sample.lineup_error_m for sample in groove
                ),
                "time_seconds": sum(
                    max(0.0, (segment.ended_at or now) - segment.started_at)
                    for segment in self.segments
                    if segment.phase is Case1Phase.GROOVE
                ),
            },
        }
        if reason is not None:
            result["reason"] = reason
        return result

    def _next_phase(
        self,
        *,
        forward_m: float,
        right_m: float,
        altitude_ft: float,
        relative_heading_deg: float,
        roll_deg: float | None,
        turn_rate_dps: float | None,
        gear_down: bool | None,
    ) -> Case1Phase:
        heading = abs(relative_heading_deg)
        roll = abs(roll_deg or 0.0)
        if self.phase is Case1Phase.UNKNOWN:
            if forward_m <= -self.profile.initial_min_distance_m and heading < 45.0:
                return Case1Phase.INITIAL
        elif self.phase is Case1Phase.INITIAL:
            if heading > 30.0 or roll > 15.0 or abs(turn_rate_dps or 0.0) > 5.0:
                return Case1Phase.BREAK
        elif self.phase is Case1Phase.BREAK:
            if heading > 135.0 and abs(right_m) > 500.0:
                return Case1Phase.DOWNWIND
        elif self.phase is Case1Phase.DOWNWIND:
            if abs(forward_m) <= self.profile.abeam_forward_window_m:
                return Case1Phase.ABEAM
        elif self.phase is Case1Phase.ABEAM:
            if 100.0 < heading < 175.0 and (
                roll > 10.0 or abs(turn_rate_dps or 0.0) > 3.0
            ):
                return Case1Phase.ONE_EIGHTY
        elif self.phase is Case1Phase.ONE_EIGHTY:
            if 60.0 <= heading <= 120.0 and forward_m < -300.0:
                return Case1Phase.NINETY
        elif self.phase is Case1Phase.NINETY:
            if (
                heading < 30.0
                and forward_m < -50.0
                and abs(right_m) < 200.0
                and gear_down is not False
            ):
                return Case1Phase.GROOVE
        elif (
            self.phase is Case1Phase.GROOVE
            and abs(forward_m) < 80.0
            and altitude_ft < 50.0
        ):
            return Case1Phase.TRAP_OR_BOLTER
        return self.phase

    def _record(self, sample: Case1Sample) -> None:
        if not self.segments or self.segments[-1].phase is not sample.phase:
            if self.segments:
                previous = self.segments[-1]
                previous.ended_at = sample.timestamp
                previous.exit_state = previous.samples[-1]
            self.segments.append(
                Case1Segment(
                    sample.phase,
                    sample.timestamp,
                    sample,
                    samples=deque([sample], maxlen=MAX_EXERCISE_SAMPLES),
                )
            )
        else:
            self.segments[-1].samples.append(sample)


def _angle_delta(target_deg: float, reference_deg: float) -> float:
    return (target_deg - reference_deg + 180.0) % 360.0 - 180.0


def _usable_value(value, now: float, stale_after: float):
    return value.value if value.usable(now, stale_after=stale_after) else None


def _mean(values) -> float | None:
    present = [float(value) for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _sample_state(sample: Case1Sample) -> dict[str, Any]:
    return {
        "timestamp": sample.timestamp,
        "forward_m": sample.forward_m,
        "right_m": sample.right_m,
        "altitude_ft": sample.altitude_ft,
        "heading_relative_deg": sample.heading_relative_deg,
        "airspeed_kt": sample.airspeed_kt,
    }
