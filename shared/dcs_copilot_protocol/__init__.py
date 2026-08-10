"""Versioned transport-neutral protocol shared by client and cloud."""

from .media import AudioFormat, MediaKind, MediaPacket
from .messages import (
    KNOWN_CONTROL_TYPES,
    PROTOCOL_VERSION,
    ControlMessage,
    ProtocolError,
    UnsupportedProtocolVersion,
)
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
    "AIRCRAFT_TOOL_VERSION",
    "ALLOWED_AIRCRAFT_STATE_FIELDS",
    "KNOWN_CONTROL_TYPES",
    "PROTOCOL_VERSION",
    "AircraftToolName",
    "AircraftToolRequest",
    "AircraftToolResult",
    "AudioFormat",
    "ControlMessage",
    "MediaKind",
    "MediaPacket",
    "ProtocolError",
    "ToolAuthorizationError",
    "ToolProtocolError",
    "UnsupportedProtocolVersion",
    "validate_tool_arguments",
]
