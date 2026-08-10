"""Versioned semantic session metadata; never raw cockpit state."""

from __future__ import annotations

from dataclasses import dataclass

from .messages import ControlMessage, ProtocolError

SESSION_METADATA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AircraftChanged:
    aircraft: str | None
    metadata_version: int = SESSION_METADATA_VERSION

    def __post_init__(self) -> None:
        if self.metadata_version != SESSION_METADATA_VERSION:
            raise ProtocolError("unsupported session metadata version")
        if self.aircraft is not None and (
            not isinstance(self.aircraft, str)
            or not self.aircraft.strip()
            or len(self.aircraft) > 64
        ):
            raise ProtocolError("aircraft must be null or a 1 to 64 character string")

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "aircraft.changed",
            {
                "metadata_version": self.metadata_version,
                "aircraft": self.aircraft.strip()
                if isinstance(self.aircraft, str)
                else None,
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> AircraftChanged:
        if message.type != "aircraft.changed":
            raise ProtocolError("expected aircraft.changed")
        if set(message.payload) != {"metadata_version", "aircraft"}:
            raise ProtocolError("aircraft.changed payload has unexpected fields")
        version = message.payload["metadata_version"]
        aircraft = message.payload["aircraft"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise ProtocolError("metadata_version must be an integer")
        if aircraft is not None and not isinstance(aircraft, str):
            raise ProtocolError("aircraft must be a string or null")
        return cls(aircraft, version)
