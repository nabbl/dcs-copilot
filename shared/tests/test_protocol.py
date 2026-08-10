from __future__ import annotations

import json

import pytest
from dcs_copilot_protocol import (
    AIRCRAFT_TOOL_VERSION,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    AudioFormat,
    ControlMessage,
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
