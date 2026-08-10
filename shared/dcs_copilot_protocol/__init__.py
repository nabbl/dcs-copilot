"""Versioned transport-neutral protocol shared by client and cloud."""

from .events import (
    AIRCRAFT_EVENT_VERSION,
    AircraftEvent,
    EventProtocolError,
)
from .habits import (
    FLIGHT_SUMMARY_VERSION,
    HABIT_RULE_IDS,
    FlightSummary,
    FlightSummaryProtocolError,
)
from .media import AudioFormat, MediaKind, MediaPacket
from .messages import (
    KNOWN_CONTROL_TYPES,
    PROTOCOL_VERSION,
    ControlMessage,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from .sessions import SESSION_METADATA_VERSION, AircraftChanged
from .tools import (
    AIRCRAFT_TOOL_VERSION,
    ALLOWED_AIRCRAFT_STATE_FIELDS,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    ToolAuthorizationError,
    ToolProtocolError,
    validate_tool_arguments,
)

__all__ = [
    "AIRCRAFT_EVENT_VERSION",
    "AIRCRAFT_TOOL_VERSION",
    "ALLOWED_AIRCRAFT_STATE_FIELDS",
    "FLIGHT_SUMMARY_VERSION",
    "HABIT_RULE_IDS",
    "KNOWN_CONTROL_TYPES",
    "PROTOCOL_VERSION",
    "SESSION_METADATA_VERSION",
    "AircraftChanged",
    "AircraftEvent",
    "AircraftToolName",
    "AircraftToolRequest",
    "AircraftToolResult",
    "AudioFormat",
    "ControlMessage",
    "EventProtocolError",
    "FlightSummary",
    "FlightSummaryProtocolError",
    "MediaKind",
    "MediaPacket",
    "ProtocolError",
    "ToolAuthorizationError",
    "ToolProtocolError",
    "UnsupportedProtocolVersion",
    "validate_tool_arguments",
]
