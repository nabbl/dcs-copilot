from __future__ import annotations

import json

from dcs_copilot.dcs.spatial_export import DcsSpatialClient, parse_spatial_datagram
from dcs_copilot_protocol import CoachTelemetry


def _payload(*, world_export: bool = True) -> bytes:
    return json.dumps(
        {
            "coach_telemetry_version": 1,
            "sequence": 1,
            "observed_at_ms": 1000,
            "capabilities": {
                "ownship_export": True,
                "world_object_export": world_export,
                "sensor_export": False,
                "cockpit_state": False,
            },
            "ownship": {
                "position": {"x": 1, "y": 2, "z": 3},
                "heading_deg": 90,
            },
            "references": (
                [
                    {
                        "object_id": "lead",
                        "object_type": "LEAD_AIRCRAFT",
                        "position": {"x": 10, "y": 20, "z": 30},
                        "heading_deg": 45,
                    }
                ]
                if world_export
                else []
            ),
        }
    ).encode()


def test_spatial_datagram_is_normalized_to_bounded_protocol() -> None:
    message = parse_spatial_datagram(_payload())

    assert isinstance(message, CoachTelemetry)
    assert message.references[0].object_id == "lead"
    assert message.to_control().type == "coach.telemetry"


def test_spatial_client_tracks_parse_errors_without_publishing_bad_data() -> None:
    received: list[CoachTelemetry] = []
    client = DcsSpatialClient(on_observation=received.append)

    client.datagram_received(b"not-json", ("127.0.0.1", 7780))
    client.datagram_received(_payload(world_export=False), ("127.0.0.1", 7780))

    assert client.parser_errors == 1
    assert len(received) == 1
    assert received[0].capabilities.world_object_export is False


def test_spatial_client_fails_closed_when_export_stream_becomes_stale() -> None:
    now = [10.0]
    received: list[CoachTelemetry] = []
    client = DcsSpatialClient(
        on_observation=received.append,
        stale_timeout=1.0,
        clock=lambda: now[0],
    )
    client.datagram_received(_payload(), ("127.0.0.1", 7780))

    now[0] = 11.1
    client._fail_closed_if_stale()

    assert len(received) == 2
    assert received[-1].capabilities.world_object_export is False
    assert received[-1].ownship is None
    assert received[-1].references == ()
