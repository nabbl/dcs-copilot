from __future__ import annotations

import math

import pytest
from dcs_copilot_cloud.coach.exercises.case1 import (
    Case1Exercise,
    Case1Phase,
    Case1Profile,
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
        object_id="carrier",
        object_type=ReferenceObjectType.CARRIER,
        position=Vec3(0.0, 0.0, 0.0),
        velocity=Vec3(10.0, 0.0, 0.0),
        heading_deg=0.0,
        timestamp=timestamp,
        source=SOURCE,
    )


def _ownship(
    *,
    forward_m: float,
    right_m: float,
    altitude_ft: float,
    heading_deg: float,
    timestamp: float,
    roll_deg: float = 0.0,
) -> OwnshipState:
    altitude_m = altitude_ft / 3.28084
    return OwnshipState(
        position=ObservedValue.observed(
            Vec3(forward_m, altitude_m, right_m), source=SOURCE, timestamp=timestamp
        ),
        velocity=ObservedValue.observed(
            Vec3(80.0, -3.0, 0.0), source=SOURCE, timestamp=timestamp
        ),
        heading_deg=ObservedValue.observed(
            heading_deg, source=SOURCE, timestamp=timestamp
        ),
        roll_deg=ObservedValue.observed(roll_deg, source=SOURCE, timestamp=timestamp),
        altitude_msl_ft=ObservedValue.observed(
            altitude_ft, source=SOURCE, timestamp=timestamp
        ),
        indicated_airspeed_kt=ObservedValue.observed(
            350.0 if timestamp == 0.0 else 145.0,
            source=SOURCE,
            timestamp=timestamp,
        ),
        vertical_speed_fpm=ObservedValue.observed(
            -500.0, source=SOURCE, timestamp=timestamp
        ),
        timestamp=timestamp,
    )


def _profile() -> Case1Profile:
    return Case1Profile(
        name="test",
        target_initial_altitude_ft=800.0,
        target_downwind_altitude_ft=600.0,
        target_downwind_abeam_nm=1.0,
        glidepath_deg=3.5,
        groove_lineup_tolerance_m=50.0,
    )


def test_case1_segments_a_synthetic_carrier_relative_pattern() -> None:
    exercise = Case1Exercise(_profile(), started_at=0.0)
    observations = [
        _ownship(
            forward_m=-2000, right_m=0, altitude_ft=800, heading_deg=0, timestamp=0
        ),
        _ownship(
            forward_m=-100,
            right_m=-100,
            altitude_ft=800,
            heading_deg=60,
            roll_deg=30,
            timestamp=1,
        ),
        _ownship(
            forward_m=-800, right_m=-1852, altitude_ft=600, heading_deg=180, timestamp=2
        ),
        _ownship(
            forward_m=0, right_m=-1852, altitude_ft=600, heading_deg=180, timestamp=3
        ),
        _ownship(
            forward_m=-300,
            right_m=-1700,
            altitude_ft=580,
            heading_deg=140,
            roll_deg=30,
            timestamp=4,
        ),
        _ownship(
            forward_m=-800,
            right_m=-900,
            altitude_ft=500,
            heading_deg=90,
            roll_deg=25,
            timestamp=5,
        ),
    ]
    desired_groove_ft = math.tan(math.radians(3.5)) * 600 * 3.28084
    observations.extend(
        [
            _ownship(
                forward_m=-600,
                right_m=20,
                altitude_ft=desired_groove_ft - 20,
                heading_deg=0,
                timestamp=6,
            ),
            _ownship(
                forward_m=-20, right_m=0, altitude_ft=20, heading_deg=0, timestamp=7
            ),
        ]
    )

    phases = []
    for timestamp, ownship in enumerate(observations):
        exercise.update(ownship, _carrier(float(timestamp)), now=float(timestamp))
        phases.append(exercise.phase)

    assert phases == [
        Case1Phase.INITIAL,
        Case1Phase.BREAK,
        Case1Phase.DOWNWIND,
        Case1Phase.ABEAM,
        Case1Phase.ONE_EIGHTY,
        Case1Phase.NINETY,
        Case1Phase.GROOVE,
        Case1Phase.TRAP_OR_BOLTER,
    ]

    debrief = exercise.stop(now=7.0)
    assert debrief["downwind"]["mean_abeam_nm"] == pytest.approx(1.0)
    assert debrief["at_180"]["altitude_ft"] == pytest.approx(580.0)
    assert debrief["groove"]["mean_glidepath_error_ft"] == pytest.approx(-20.0)
    assert debrief["groove"]["mean_lineup_error_m"] == pytest.approx(20.0)
    assert [segment["phase"] for segment in debrief["segments"]] == [
        phase.value for phase in phases
    ]
