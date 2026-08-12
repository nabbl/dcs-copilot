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


@dataclass(frozen=True, slots=True)
class CockpitEntered:
    aircraft: str
    metadata_version: int = SESSION_METADATA_VERSION

    def __post_init__(self) -> None:
        if self.metadata_version != SESSION_METADATA_VERSION:
            raise ProtocolError("unsupported session metadata version")
        if (
            not isinstance(self.aircraft, str)
            or not self.aircraft.strip()
            or len(self.aircraft) > 64
        ):
            raise ProtocolError("aircraft must be a 1 to 64 character string")

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "cockpit.entered",
            {
                "metadata_version": self.metadata_version,
                "aircraft": self.aircraft.strip(),
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> CockpitEntered:
        if message.type != "cockpit.entered":
            raise ProtocolError("expected cockpit.entered")
        if set(message.payload) != {"metadata_version", "aircraft"}:
            raise ProtocolError("cockpit.entered payload has unexpected fields")
        version = message.payload["metadata_version"]
        aircraft = message.payload["aircraft"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise ProtocolError("metadata_version must be an integer")
        if not isinstance(aircraft, str):
            raise ProtocolError("aircraft must be a string")
        return cls(aircraft, version)
