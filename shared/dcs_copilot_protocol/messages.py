"""JSON control-message envelope for protocol version 1."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

PROTOCOL_VERSION = 1

KNOWN_CONTROL_TYPES = frozenset(
    {
        "hello",
        "authenticate",
        "session.start",
        "session.end",
        "ptt.start",
        "audio.input",
        "ptt.end",
        "assistant.text",
        "audio.output",
        "assistant.interrupt",
        "tool.request",
        "tool.result",
        "aircraft.changed",
        "flight.summary",
        "event.raised",
        "event.resolved",
        "event",
        "connection.status",
        "error",
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
        if not self.type:
            raise ProtocolError("control message type cannot be empty")
        if not self.message_id:
            raise ProtocolError("control message_id cannot be empty")
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
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"invalid control JSON: {exc.msg}") from exc
        if not isinstance(document, dict):
            raise ProtocolError("control message must be a JSON object")
        version = document.get("protocol_version")
        if not isinstance(version, int):
            raise ProtocolError("protocol_version must be an integer")
        if version != PROTOCOL_VERSION:
            raise UnsupportedProtocolVersion(f"unsupported protocol version {version}")
        message_type = document.get("type")
        message_id = document.get("message_id")
        correlation_id = document.get("correlation_id")
        payload = document.get("payload", {})
        if not isinstance(message_type, str) or not message_type:
            raise ProtocolError("control message type must be a non-empty string")
        if not isinstance(message_id, str) or not message_id:
            raise ProtocolError("message_id must be a non-empty string")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ProtocolError("correlation_id must be a string or null")
        if not isinstance(payload, dict):
            raise ProtocolError("payload must be a JSON object")
        return cls(
            message_type,
            payload,
            message_id,
            correlation_id,
            version,
        )
