"""Versioned semantic aircraft events for bounded proactive speech."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .messages import ControlMessage, ProtocolError

AIRCRAFT_EVENT_VERSION = 1
EVENT_CONTROL_TYPES = frozenset({"event.raised", "event.resolved"})
EVENT_STATUSES = frozenset({"RAISED", "RESOLVED", "DISABLED"})
EVENT_SEVERITIES = frozenset({"INFO", "ADVISORY", "WARNING", "CRITICAL"})


class EventProtocolError(ProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class AircraftEvent:
    event_id: str
    rule_id: str
    status: str
    severity: str
    aircraft: str
    flight_phase: str | None
    message: str
    data: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.event_id or len(self.event_id) > 128:
            raise EventProtocolError("event_id must contain 1 to 128 characters")
        if not self.rule_id or len(self.rule_id) > 128:
            raise EventProtocolError("rule_id must contain 1 to 128 characters")
        if self.status not in EVENT_STATUSES:
            raise EventProtocolError(f"invalid aircraft event status {self.status}")
        if self.severity not in EVENT_SEVERITIES:
            raise EventProtocolError(f"invalid aircraft event severity {self.severity}")
        if not self.aircraft or len(self.aircraft) > 128:
            raise EventProtocolError("event aircraft must contain 1 to 128 characters")
        if self.flight_phase is not None and (
            not self.flight_phase or len(self.flight_phase) > 64
        ):
            raise EventProtocolError(
                "event flight_phase must contain 1 to 64 characters"
            )
        if not self.message or len(self.message) > 240:
            raise EventProtocolError("event message must contain 1 to 240 characters")
        if not isinstance(self.data, dict) or len(self.data) > 16:
            raise EventProtocolError("event data must be an object with at most 16 fields")
        if any(
            not isinstance(key, str) or not key or len(key) > 128
            for key in self.data
        ):
            raise EventProtocolError("event data keys must contain 1 to 128 characters")
        try:
            encoded_data = json.dumps(self.data, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise EventProtocolError("event data must be JSON serializable") from exc
        if len(encoded_data.encode("utf-8")) > 4_096:
            raise EventProtocolError("event data cannot exceed 4096 encoded bytes")

    @property
    def control_type(self) -> str:
        return "event.raised" if self.status == "RAISED" else "event.resolved"

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            self.control_type,
            {
                "event_version": AIRCRAFT_EVENT_VERSION,
                "event_id": self.event_id,
                "rule_id": self.rule_id,
                "status": self.status,
                "severity": self.severity,
                "aircraft": self.aircraft,
                "flight_phase": self.flight_phase,
                "message": self.message,
                "data": self.data,
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> AircraftEvent:
        if message.type not in EVENT_CONTROL_TYPES:
            raise EventProtocolError("expected event.raised or event.resolved")
        expected = {
            "event_version",
            "event_id",
            "rule_id",
            "status",
            "severity",
            "aircraft",
            "flight_phase",
            "message",
            "data",
        }
        unknown = sorted(message.payload.keys() - expected)
        missing = sorted(expected - message.payload.keys())
        if missing:
            raise EventProtocolError(
                "aircraft event missing fields: " + ", ".join(missing)
            )
        if unknown:
            raise EventProtocolError(
                "aircraft event contains unknown fields: " + ", ".join(unknown)
            )
        version = message.payload.get("event_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != AIRCRAFT_EVENT_VERSION
        ):
            raise EventProtocolError(f"unsupported aircraft event version {version}")
        event_id = message.payload.get("event_id")
        rule_id = message.payload.get("rule_id")
        status = message.payload.get("status")
        severity = message.payload.get("severity")
        aircraft = message.payload.get("aircraft")
        phase = message.payload.get("flight_phase")
        event_message = message.payload.get("message")
        data = message.payload.get("data")
        if not isinstance(event_id, str) or not isinstance(rule_id, str):
            raise EventProtocolError("event identifiers must be strings")
        if not isinstance(status, str) or not isinstance(severity, str):
            raise EventProtocolError("event status and severity must be strings")
        if not isinstance(aircraft, str):
            raise EventProtocolError("event aircraft must be a string")
        if phase is not None and not isinstance(phase, str):
            raise EventProtocolError("event flight_phase must be a string or null")
        if not isinstance(event_message, str):
            raise EventProtocolError("event message must be a string")
        if not isinstance(data, dict):
            raise EventProtocolError("event data must be an object")
        event = cls(
            event_id,
            rule_id,
            status,
            severity,
            aircraft,
            phase,
            event_message,
            data,
        )
        if message.type != event.control_type:
            raise EventProtocolError("event control type does not match event status")
        return event
