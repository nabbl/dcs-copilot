from __future__ import annotations

import json

import pytest
from dcs_copilot_protocol import (
    AIRCRAFT_EVENT_VERSION,
    AIRCRAFT_TOOL_VERSION,
    FLIGHT_SUMMARY_VERSION,
    AircraftChanged,
    AircraftEvent,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    AudioFormat,
    CockpitEntered,
    ControlMessage,
    EventProtocolError,
    FlightSummary,
    FlightSummaryProtocolError,
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


def test_cockpit_entered_is_versioned_and_requires_an_aircraft() -> None:
    message = CockpitEntered("FA-18C_hornet").to_control()
    assert message.type == "cockpit.entered"
    assert CockpitEntered.from_control(message).aircraft == "FA-18C_hornet"
    with pytest.raises(ProtocolError, match="1 to 64"):
        CockpitEntered("")
    with pytest.raises(ProtocolError, match="unexpected fields"):
        CockpitEntered.from_control(
            ControlMessage(
                "cockpit.entered",
                {
                    "metadata_version": 1,
                    "aircraft": "FA-18C_hornet",
                    "raw_state": {},
                },
            )
        )


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


def test_checklist_tools_round_trip_and_validate_bounded_results() -> None:
    request = AircraftToolRequest.create(
        "get_checklist_status",
        {
            "checklist_id": "fa18c_startup",
            "stage": "before-taxi",
            "include_complete": True,
        },
        request_id="checklist-request",
    )
    assert AircraftToolRequest.from_control(request.to_control()) == request
    result = AircraftToolResult.success(
        request,
        {
            "available": True,
            "checklist_id": "fa18c_startup",
            "aircraft": "FA-18C_hornet",
            "stage": "before-taxi",
            "complete": False,
            "items": [
                {
                    "id": "obogs_on",
                    "label": "OBOGS",
                    "status": "incomplete",
                    "expected": True,
                    "actual": False,
                    "reason": "obogs_on is False, expected True",
                    "verification_type": "state",
                    "observed_at": 1.0,
                }
            ],
        },
    )
    assert AircraftToolResult.from_control(result.to_control()) == result

    with pytest.raises(ToolProtocolError, match="status"):
        AircraftToolResult.success(
            request,
            {
                "available": True,
                "checklist_id": "fa18c_startup",
                "aircraft": "FA-18C_hornet",
                "stage": "before-taxi",
                "complete": False,
                "items": [
                    {
                        "id": "obogs_on",
                        "label": "OBOGS",
                        "status": "wrong",
                        "expected": True,
                        "actual": False,
                        "reason": "bad",
                        "verification_type": "state",
                        "observed_at": 1.0,
                    }
                ],
            },
        )


def test_guided_checklist_tools_validate_arguments() -> None:
    assert AircraftToolRequest.create(
        "start_guided_checklist",
        {"checklist_id": "fa18c_startup", "stage": "before-taxi"},
    ).arguments == {"checklist_id": "fa18c_startup", "stage": "before-taxi"}
    assert AircraftToolRequest.create(
        "confirm_manual_checklist_item",
        {"item_id": "helmet"},
    ).arguments == {"item_id": "helmet"}
    with pytest.raises(ToolProtocolError, match="item_id"):
        AircraftToolRequest.create("confirm_manual_checklist_item", {"item_id": ""})


def test_aircraft_changed_is_versioned_and_semantic_only() -> None:
    message = AircraftChanged("F/A-18C").to_control()
    assert message.payload == {"metadata_version": 1, "aircraft": "F/A-18C"}
    assert AircraftChanged.from_control(message).aircraft == "F/A-18C"
    with pytest.raises(ProtocolError, match="unexpected fields"):
        AircraftChanged.from_control(
            ControlMessage(
                "aircraft.changed",
                {
                    "metadata_version": 1,
                    "aircraft": "F/A-18C",
                    "cockpit": {"raw": "forbidden"},
                },
            )
        )


def test_flight_summary_is_versioned_allowlisted_and_semantic_only() -> None:
    summary = FlightSummary(
        "5a9a86e7-2de1-44da-841c-09177d05c09d",
        "FA-18C_hornet",
        {"FA18_REFUELING_PROBE_LEFT_OUT": 2, "FA18_MASTER_CAUTION": 0},
    )
    control = summary.to_control()
    assert control.type == "flight.summary"
    assert set(control.payload) == {
        "summary_version",
        "summary_id",
        "aircraft",
        "rules",
    }
    assert FlightSummary.from_control(control) == summary

    with pytest.raises(FlightSummaryProtocolError, match="not allowlisted"):
        FlightSummary(summary.summary_id, summary.aircraft, {"RAW_COCKPIT": 1})
    with pytest.raises(FlightSummaryProtocolError, match="between"):
        FlightSummary(
            summary.summary_id,
            summary.aircraft,
            {"FA18_MASTER_CAUTION": True},
        )
    with pytest.raises(FlightSummaryProtocolError, match="unexpected fields"):
        FlightSummary.from_control(
            ControlMessage(
                "flight.summary",
                {
                    **control.payload,
                    "raw_telemetry": {"address": 1234},
                },
            )
        )
    with pytest.raises(FlightSummaryProtocolError, match="unsupported"):
        FlightSummary.from_control(
            ControlMessage(
                "flight.summary",
                {**control.payload, "summary_version": FLIGHT_SUMMARY_VERSION + 1},
            )
        )
