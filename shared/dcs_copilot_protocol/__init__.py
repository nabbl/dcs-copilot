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

MARA_VERSION = "0.1.0"
MARA_API_VERSION = "1"

__all__ = [
    "COACH_TELEMETRY_VERSION",
    "KNOWN_CONTROL_TYPES",
    "MARA_API_VERSION",
    "MARA_VERSION",
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
