"""JSON control-message envelope for protocol version 2."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

PROTOCOL_VERSION = 2

_MAX_ENVELOPE_BYTES = 256 * 1024  # 256 KiB
_MAX_ID_LENGTH = 128
_MAX_PAYLOAD_FIELDS = 64
_KNOWN_TOP_LEVEL_FIELDS = frozenset(
    {"protocol_version", "type", "message_id", "correlation_id", "payload"}
)

KNOWN_CONTROL_TYPES = frozenset(
    {
        "hello",
        "authenticate",
        "session.start",
        "session.end",
        "ptt.start",
        "ptt.end",
        "pilot.text",
        "assistant.text",
        "audio.input",
        "audio.output",
        "assistant.interrupt",
        "connection.status",
        "error",
        "event",
        "telemetry.catalog",
        "telemetry.snapshot",
        "telemetry.delta",
        "coach.telemetry",
    }
)


class ProtocolError(ValueError):
    pass


class UnsupportedProtocolVersion(ProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class ControlMessage:
    """Validated base envelope; unknown message types remain representable."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.type or len(self.type) > _MAX_ID_LENGTH:
            raise ProtocolError(
                f"control message type must be 1 to {_MAX_ID_LENGTH} characters"
            )
        if not self.message_id or len(self.message_id) > _MAX_ID_LENGTH:
            raise ProtocolError(f"message_id must be 1 to {_MAX_ID_LENGTH} characters")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str)
            or len(self.correlation_id) > _MAX_ID_LENGTH
        ):
            raise ProtocolError(
                f"correlation_id must be a string of at most {_MAX_ID_LENGTH} characters"
            )
        if len(self.payload) > _MAX_PAYLOAD_FIELDS:
            raise ProtocolError(
                f"payload may not exceed {_MAX_PAYLOAD_FIELDS} top-level fields"
            )
        if self.protocol_version != PROTOCOL_VERSION:
            raise UnsupportedProtocolVersion(
                f"unsupported protocol version {self.protocol_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        encoded: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "message_id": self.message_id,
            "payload": self.payload,
        }
        if self.correlation_id is not None:
            encoded["correlation_id"] = self.correlation_id
        return encoded

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> ControlMessage:
        if len(raw.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
            raise ProtocolError(
                f"control message exceeds {_MAX_ENVELOPE_BYTES // 1024} KiB limit"
            )
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"invalid control JSON: {exc.msg}") from exc
        if not isinstance(document, dict):
            raise ProtocolError("control message must be a JSON object")
        unknown = sorted(document.keys() - _KNOWN_TOP_LEVEL_FIELDS)
        if unknown:
            raise ProtocolError(
                "control message contains unknown top-level fields: "
                + ", ".join(unknown)
            )
        version = document.get("protocol_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ProtocolError("protocol_version must be an integer")
        if version != PROTOCOL_VERSION:
            raise UnsupportedProtocolVersion(f"unsupported protocol version {version}")
        message_type = document.get("type")
        message_id = document.get("message_id")
        correlation_id = document.get("correlation_id")
        payload = document.get("payload", {})
        if not isinstance(message_type, str) or not message_type:
            raise ProtocolError("control message type must be a non-empty string")
        if len(message_type) > _MAX_ID_LENGTH:
            raise ProtocolError(
                f"control message type may not exceed {_MAX_ID_LENGTH} characters"
            )
        if not isinstance(message_id, str) or not message_id:
            raise ProtocolError("message_id must be a non-empty string")
        if len(message_id) > _MAX_ID_LENGTH:
            raise ProtocolError(
                f"message_id may not exceed {_MAX_ID_LENGTH} characters"
            )
        if correlation_id is not None:
            if not isinstance(correlation_id, str):
                raise ProtocolError("correlation_id must be a string or null")
            if len(correlation_id) > _MAX_ID_LENGTH:
                raise ProtocolError(
                    f"correlation_id may not exceed {_MAX_ID_LENGTH} characters"
                )
        if not isinstance(payload, dict):
            raise ProtocolError("payload must be a JSON object")
        if len(payload) > _MAX_PAYLOAD_FIELDS:
            raise ProtocolError(
                f"payload may not exceed {_MAX_PAYLOAD_FIELDS} top-level fields"
            )
        return cls(
            message_type,
            payload,
            message_id,
            correlation_id,
            version,
        )
