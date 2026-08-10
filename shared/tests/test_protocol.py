from __future__ import annotations

import json

import pytest
from dcs_copilot_protocol import (
    AIRCRAFT_EVENT_VERSION,
    AIRCRAFT_TOOL_VERSION,
    AircraftEvent,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    AudioFormat,
    ControlMessage,
    EventProtocolError,
    MediaKind,
    MediaPacket,
    ProtocolError,
    ToolAuthorizationError,
    ToolProtocolError,
    UnsupportedProtocolVersion,
)


def test_control_envelope_round_trip_and_unknown_type() -> None:
    original = ControlMessage(
        "future.message",
        {"value": 7},
        message_id="message-1",
        correlation_id="request-1",
    )
    decoded = ControlMessage.from_json(original.to_json())
    assert decoded == original
    assert decoded.type == "future.message"


def test_control_envelope_rejects_unsupported_version() -> None:
    raw = json.dumps(
        {
            "protocol_version": 99,
            "type": "hello",
            "message_id": "message-1",
            "payload": {},
        }
    )
    with pytest.raises(UnsupportedProtocolVersion):
        ControlMessage.from_json(raw)


def test_binary_media_envelope_round_trip() -> None:
    packet = MediaPacket(MediaKind.AUDIO_INPUT, 42, 123456, b"\x01\x02" * 320)
    assert MediaPacket.from_bytes(packet.to_bytes()) == packet
    with pytest.raises(ProtocolError, match="shorter"):
        MediaPacket.from_bytes(b"bad")


def test_audio_format_is_pcm_v1_and_validated() -> None:
    audio_format = AudioFormat(sample_rate=16_000, channels=1, chunk_ms=20)
    assert AudioFormat.from_dict(audio_format.to_dict()) == audio_format
    with pytest.raises(ProtocolError, match="pcm_s16le"):
        AudioFormat.from_dict(
            {
                "encoding": "opus",
                "sample_rate": 16_000,
                "channels": 1,
                "chunk_ms": 20,
            }
        )


def test_versioned_aircraft_tool_request_and_correlated_result_round_trip() -> None:
    request = AircraftToolRequest.create(
        AircraftToolName.GET_AIRCRAFT_STATE,
        {"fields": ["refueling_probe", "master_caution"]},
        request_id="request-1",
    )
    decoded_request = AircraftToolRequest.from_control(request.to_control())
    assert decoded_request == request
    response = AircraftToolResult.success(
        request,
        {
            "fields": {
                "refueling_probe": {
                    "status": "AVAILABLE",
                    "value": True,
                    "updated_at": 10.0,
                    "source": "test",
                }
            }
        },
    )
    control = response.to_control()
    assert control.correlation_id == "request-1"
    assert AircraftToolResult.from_control(control) == response


def test_aircraft_tool_protocol_rejects_unknown_tools_fields_and_versions() -> None:
    with pytest.raises(ToolAuthorizationError, match="not allowed"):
        AircraftToolRequest.create("run_shell", {})
    with pytest.raises(ToolAuthorizationError, match="raw"):
        AircraftToolRequest.create("get_aircraft_state", {"fields": ["raw"]})
    with pytest.raises(ToolProtocolError, match="unknown fields"):
        AircraftToolRequest.create("get_active_issues", {"command": "anything"})
    invalid_version = ControlMessage(
        "tool.request",
        {
            "tool_version": AIRCRAFT_TOOL_VERSION + 1,
            "tool": "get_flight_phase",
            "arguments": {},
        },
    )
    with pytest.raises(ToolProtocolError, match="unsupported aircraft tool version"):
        AircraftToolRequest.from_control(invalid_version)


def test_tool_result_requires_a_correlation_id() -> None:
    message = ControlMessage(
        "tool.result",
        {
            "tool_version": AIRCRAFT_TOOL_VERSION,
            "tool": "get_flight_phase",
            "ok": True,
            "result": {"available": False, "flight_phase": None},
        },
    )
    with pytest.raises(ToolProtocolError, match="correlation_id"):
        AircraftToolResult.from_control(message)


def test_tool_result_rejects_a_value_marked_unavailable() -> None:
    request = AircraftToolRequest.create(
        "get_aircraft_state",
        {"fields": ["fuel_quantity"]},
    )
    with pytest.raises(ToolProtocolError, match="must have a null value"):
        AircraftToolResult.success(
            request,
            {
                "fields": {
                    "fuel_quantity": {
                        "status": "UNAVAILABLE",
                        "value": 5000,
                        "updated_at": None,
                        "source": None,
                    }
                }
            },
        )


def test_semantic_aircraft_event_round_trip_preserves_only_bounded_data() -> None:
    raised = AircraftEvent(
        event_id="event-1",
        rule_id="FA18_REFUELING_PROBE_LEFT_OUT",
        status="RAISED",
        severity="ADVISORY",
        aircraft="FA-18C_hornet",
        flight_phase="CRUISE",
        message="Refueling probe is still out.",
        data={"flight_phase": "CRUISE"},
    )
    raised_control = raised.to_control()
    assert raised_control.type == "event.raised"
    assert AircraftEvent.from_control(raised_control) == raised

    resolved = AircraftEvent(
        event_id=raised.event_id,
        rule_id=raised.rule_id,
        status="RESOLVED",
        severity=raised.severity,
        aircraft=raised.aircraft,
        flight_phase=raised.flight_phase,
        message=raised.message,
        data={},
    )
    assert resolved.to_control().type == "event.resolved"
    assert AircraftEvent.from_control(resolved.to_control()) == resolved


def test_semantic_event_rejects_version_mismatch_and_status_spoofing() -> None:
    payload = {
        "event_version": AIRCRAFT_EVENT_VERSION + 1,
        "event_id": "event-1",
        "rule_id": "FA18_MASTER_CAUTION",
        "status": "RAISED",
        "severity": "WARNING",
        "aircraft": "FA-18C_hornet",
        "flight_phase": None,
        "message": "Master Caution is on.",
        "data": {},
    }
    with pytest.raises(EventProtocolError, match="unsupported"):
        AircraftEvent.from_control(ControlMessage("event.raised", payload))

    payload["event_version"] = AIRCRAFT_EVENT_VERSION
    payload["status"] = "RESOLVED"
    with pytest.raises(EventProtocolError, match="does not match"):
        AircraftEvent.from_control(ControlMessage("event.raised", payload))


def test_semantic_event_data_is_strictly_bounded() -> None:
    with pytest.raises(EventProtocolError, match="4096"):
        AircraftEvent(
            event_id="event-1",
            rule_id="FA18_MASTER_CAUTION",
            status="RAISED",
            severity="WARNING",
            aircraft="FA-18C_hornet",
            flight_phase=None,
            message="Master Caution is on.",
            data={"detail": "x" * 5_000},
        )


def test_recent_events_tool_accepts_only_typed_semantic_rule_events() -> None:
    request = AircraftToolRequest.create(
        "get_recent_events",
        {"seconds": 30, "limit": 5},
    )
    result = AircraftToolResult.success(
        request,
        {
            "available": True,
            "events": [
                {
                    "event_id": "event-1",
                    "rule_id": "FA18_MASTER_CAUTION",
                    "status": "RAISED",
                    "severity": "WARNING",
                    "aircraft": "FA-18C_hornet",
                    "flight_phase": "CRUISE",
                    "message": "Master Caution is on.",
                    "data": {},
                    "seconds_ago": 1.5,
                }
            ],
        },
    )
    assert AircraftToolResult.from_control(result.to_control()) == result
