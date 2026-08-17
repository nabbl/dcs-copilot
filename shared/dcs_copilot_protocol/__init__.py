"""Versioned transport-neutral protocol shared by client and cloud."""

from .coach import (
    COACH_TELEMETRY_VERSION,
    CoachCapabilitiesPayload,
    CoachReferencePayload,
    CoachTelemetry,
    CoachVec3,
    OwnshipPayload,
)
from .media import AudioFormat, MediaKind, MediaPacket
from .messages import (
    KNOWN_CONTROL_TYPES,
    PROTOCOL_VERSION,
    ControlMessage,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from .telemetry import (
    TELEMETRY_VERSION,
    CatalogEntry,
    ControlIdentity,
    DecodedValue,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetryProtocolError,
    TelemetrySnapshot,
)

__all__ = [
    "COACH_TELEMETRY_VERSION",
    "KNOWN_CONTROL_TYPES",
    "PROTOCOL_VERSION",
    "TELEMETRY_VERSION",
    "AudioFormat",
    "CatalogEntry",
    "CoachCapabilitiesPayload",
    "CoachReferencePayload",
    "CoachTelemetry",
    "CoachVec3",
    "ControlIdentity",
    "ControlMessage",
    "DecodedValue",
    "MediaKind",
    "MediaPacket",
    "OwnshipPayload",
    "ProtocolError",
    "TelemetryCatalog",
    "TelemetryDelta",
    "TelemetryProtocolError",
    "TelemetrySnapshot",
    "UnsupportedProtocolVersion",
]
