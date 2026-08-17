"""Versioned transport-neutral protocol shared by client and cloud."""

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
    "KNOWN_CONTROL_TYPES",
    "MARA_API_VERSION",
    "MARA_VERSION",
    "PROTOCOL_VERSION",
    "TELEMETRY_VERSION",
    "AudioFormat",
    "CatalogEntry",
    "ControlIdentity",
    "ControlMessage",
    "DecodedValue",
    "MediaKind",
    "MediaPacket",
    "ProtocolError",
    "TelemetryCatalog",
    "TelemetryDelta",
    "TelemetryProtocolError",
    "TelemetrySnapshot",
    "UnsupportedProtocolVersion",
]
