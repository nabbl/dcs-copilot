from __future__ import annotations

import pytest
from dcs_copilot_protocol import ControlMessage, ProtocolError
from dcs_copilot_protocol.coach import (
    CoachCapabilitiesPayload,
    CoachReferencePayload,
    CoachTelemetry,
    CoachVec3,
    OwnshipPayload,
)


def _message(*, world_export: bool = True) -> CoachTelemetry:
    return CoachTelemetry(
        sequence=3,
        observed_at_ms=1234,
        capabilities=CoachCapabilitiesPayload(
            ownship_export=True,
            world_object_export=world_export,
            sensor_export=False,
            cockpit_state=True,
        ),
        ownship=OwnshipPayload(
            position=CoachVec3(1.0, 2.0, 3.0),
            velocity=CoachVec3(4.0, 5.0, 6.0),
            heading_deg=90.0,
            altitude_msl_ft=600.0,
        ),
        references=(
            CoachReferencePayload(
                object_id="lead-1",
                object_type="LEAD_AIRCRAFT",
                position=CoachVec3(10.0, 20.0, 30.0),
                heading_deg=45.0,
                name="Lead",
            ),
        ),
    )


def test_coach_telemetry_round_trips_as_a_bounded_control_message() -> None:
    original = _message()

    decoded = CoachTelemetry.from_control(
        ControlMessage.from_json(original.to_control().to_json())
    )

    assert decoded == original
    assert decoded.to_control().type == "coach.telemetry"


def test_protocol_rejects_references_when_dcs_world_export_is_blocked() -> None:
    with pytest.raises(ProtocolError, match="world-object export is unavailable"):
        _message(world_export=False)
