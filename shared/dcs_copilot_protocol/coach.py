"""Bounded normalized spatial-observation wire schema."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any

from .messages import ControlMessage, ProtocolError

COACH_TELEMETRY_VERSION = 1
_MAX_SEQUENCE = 2**53 - 1
_MAX_REFERENCES = 2
_REFERENCE_TYPES = frozenset({"LEAD_AIRCRAFT", "CARRIER"})


def _finite(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ProtocolError(f"{name} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ProtocolError(f"{name} must be finite")
    return converted


def _optional_finite(value: object, name: str) -> float | None:
    return None if value is None else _finite(value, name)


def _exact(
    data: object, allowed: set[str], required: set[str], name: str
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProtocolError(f"{name} must be an object")
    unknown = sorted(set(data) - allowed)
    missing = sorted(required - set(data))
    if unknown:
        raise ProtocolError(f"{name} contains unknown fields: {', '.join(unknown)}")
    if missing:
        raise ProtocolError(f"{name} is missing fields: {', '.join(missing)}")
    return data


@dataclass(frozen=True, slots=True)
class CoachVec3:
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            _finite(getattr(self, name), name)

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, value: object) -> CoachVec3:
        data = _exact(value, {"x", "y", "z"}, {"x", "y", "z"}, "vector")
        return cls(
            _finite(data["x"], "vector.x"),
            _finite(data["y"], "vector.y"),
            _finite(data["z"], "vector.z"),
        )


@dataclass(frozen=True, slots=True)
class CoachCapabilitiesPayload:
    ownship_export: bool
    world_object_export: bool
    sensor_export: bool
    cockpit_state: bool

    def __post_init__(self) -> None:
        if any(not isinstance(getattr(self, item.name), bool) for item in fields(self)):
            raise ProtocolError("Coach capability flags must be booleans")

    def to_dict(self) -> dict[str, bool]:
        return {item.name: getattr(self, item.name) for item in fields(self)}

    @classmethod
    def from_dict(cls, value: object) -> CoachCapabilitiesPayload:
        names = {item.name for item in fields(cls)}
        data = _exact(value, names, names, "capabilities")
        return cls(**{name: data[name] for name in names})


@dataclass(frozen=True, slots=True)
class OwnshipPayload:
    position: CoachVec3
    velocity: CoachVec3 | None = None
    heading_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    altitude_msl_ft: float | None = None
    altitude_agl_ft: float | None = None
    indicated_airspeed_kt: float | None = None
    vertical_speed_fpm: float | None = None
    aoa_deg: float | None = None
    g_force: float | None = None
    gear_down: bool | None = None

    def __post_init__(self) -> None:
        numeric = (
            "heading_deg",
            "pitch_deg",
            "roll_deg",
            "altitude_msl_ft",
            "altitude_agl_ft",
            "indicated_airspeed_kt",
            "vertical_speed_fpm",
            "aoa_deg",
            "g_force",
        )
        for name in numeric:
            _optional_finite(getattr(self, name), f"ownship.{name}")
        if self.gear_down is not None and not isinstance(self.gear_down, bool):
            raise ProtocolError("ownship.gear_down must be boolean or null")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"position": self.position.to_dict()}
        for item in fields(self):
            if item.name == "position":
                continue
            value = getattr(self, item.name)
            if value is not None:
                result[item.name] = (
                    value.to_dict() if isinstance(value, CoachVec3) else value
                )
        return result

    @classmethod
    def from_dict(cls, value: object) -> OwnshipPayload:
        names = {item.name for item in fields(cls)}
        data = _exact(value, names, {"position"}, "ownship")
        gear_down = data.get("gear_down")
        if gear_down is not None and not isinstance(gear_down, bool):
            raise ProtocolError("ownship.gear_down must be boolean or null")
        return cls(
            position=CoachVec3.from_dict(data["position"]),
            velocity=(
                CoachVec3.from_dict(data["velocity"])
                if data.get("velocity") is not None
                else None
            ),
            heading_deg=_optional_finite(
                data.get("heading_deg"), "ownship.heading_deg"
            ),
            pitch_deg=_optional_finite(data.get("pitch_deg"), "ownship.pitch_deg"),
            roll_deg=_optional_finite(data.get("roll_deg"), "ownship.roll_deg"),
            altitude_msl_ft=_optional_finite(
                data.get("altitude_msl_ft"), "ownship.altitude_msl_ft"
            ),
            altitude_agl_ft=_optional_finite(
                data.get("altitude_agl_ft"), "ownship.altitude_agl_ft"
            ),
            indicated_airspeed_kt=_optional_finite(
                data.get("indicated_airspeed_kt"), "ownship.indicated_airspeed_kt"
            ),
            vertical_speed_fpm=_optional_finite(
                data.get("vertical_speed_fpm"), "ownship.vertical_speed_fpm"
            ),
            aoa_deg=_optional_finite(data.get("aoa_deg"), "ownship.aoa_deg"),
            g_force=_optional_finite(data.get("g_force"), "ownship.g_force"),
            gear_down=gear_down,
        )


@dataclass(frozen=True, slots=True)
class CoachReferencePayload:
    object_id: str
    object_type: str
    position: CoachVec3
    heading_deg: float
    velocity: CoachVec3 | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.object_id or len(self.object_id) > 128:
            raise ProtocolError("reference object_id must contain 1 to 128 characters")
        if self.object_type not in _REFERENCE_TYPES:
            raise ProtocolError("reference object_type is not supported")
        _finite(self.heading_deg, "reference.heading_deg")
        _optional_finite(self.pitch_deg, "reference.pitch_deg")
        _optional_finite(self.roll_deg, "reference.roll_deg")
        if self.name is not None and len(self.name) > 128:
            raise ProtocolError("reference name may not exceed 128 characters")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "position": self.position.to_dict(),
            "heading_deg": self.heading_deg,
        }
        for name in ("velocity", "pitch_deg", "roll_deg", "name"):
            value = getattr(self, name)
            if value is not None:
                result[name] = (
                    value.to_dict() if isinstance(value, CoachVec3) else value
                )
        return result

    @classmethod
    def from_dict(cls, value: object) -> CoachReferencePayload:
        names = {item.name for item in fields(cls)}
        required = {"object_id", "object_type", "position", "heading_deg"}
        data = _exact(value, names, required, "reference")
        object_id = data["object_id"]
        object_type = data["object_type"]
        name = data.get("name")
        if not isinstance(object_id, str) or not isinstance(object_type, str):
            raise ProtocolError("reference identifiers must be strings")
        if name is not None and not isinstance(name, str):
            raise ProtocolError("reference name must be a string or null")
        return cls(
            object_id=object_id,
            object_type=object_type,
            position=CoachVec3.from_dict(data["position"]),
            heading_deg=_finite(data["heading_deg"], "reference.heading_deg"),
            velocity=(
                CoachVec3.from_dict(data["velocity"])
                if data.get("velocity") is not None
                else None
            ),
            pitch_deg=_optional_finite(data.get("pitch_deg"), "reference.pitch_deg"),
            roll_deg=_optional_finite(data.get("roll_deg"), "reference.roll_deg"),
            name=name,
        )


@dataclass(frozen=True, slots=True)
class CoachTelemetry:
    sequence: int
    observed_at_ms: int
    capabilities: CoachCapabilitiesPayload
    ownship: OwnshipPayload | None = None
    references: tuple[CoachReferencePayload, ...] = ()
    coach_telemetry_version: int = COACH_TELEMETRY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or not 0 <= self.sequence <= _MAX_SEQUENCE
        ):
            raise ProtocolError(
                "Coach sequence must be a nonnegative JSON-safe integer"
            )
        if (
            not isinstance(self.observed_at_ms, int)
            or isinstance(self.observed_at_ms, bool)
            or self.observed_at_ms < 0
        ):
            raise ProtocolError("Coach observed_at_ms must be nonnegative")
        if self.coach_telemetry_version != COACH_TELEMETRY_VERSION:
            raise ProtocolError("unsupported Coach telemetry version")
        if self.ownship is not None and not self.capabilities.ownship_export:
            raise ProtocolError(
                "ownship data is present while ownship export is unavailable"
            )
        if self.references and not self.capabilities.world_object_export:
            raise ProtocolError(
                "references are present while world-object export is unavailable"
            )
        if len(self.references) > _MAX_REFERENCES:
            raise ProtocolError(
                f"Coach telemetry accepts at most {_MAX_REFERENCES} references"
            )
        types = [reference.object_type for reference in self.references]
        if len(types) != len(set(types)):
            raise ProtocolError("Coach telemetry contains duplicate reference types")

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "coach.telemetry",
            {
                "coach_telemetry_version": self.coach_telemetry_version,
                "sequence": self.sequence,
                "observed_at_ms": self.observed_at_ms,
                "capabilities": self.capabilities.to_dict(),
                "ownship": self.ownship.to_dict() if self.ownship else None,
                "references": [reference.to_dict() for reference in self.references],
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> CoachTelemetry:
        if message.type != "coach.telemetry":
            raise ProtocolError("expected coach.telemetry message")
        names = {
            "coach_telemetry_version",
            "sequence",
            "observed_at_ms",
            "capabilities",
            "ownship",
            "references",
        }
        data = _exact(message.payload, names, names, "Coach telemetry payload")
        references = data["references"]
        if not isinstance(references, list):
            raise ProtocolError("Coach references must be an array")
        return cls(
            sequence=data["sequence"],
            observed_at_ms=data["observed_at_ms"],
            capabilities=CoachCapabilitiesPayload.from_dict(data["capabilities"]),
            ownship=(
                OwnshipPayload.from_dict(data["ownship"])
                if data["ownship"] is not None
                else None
            ),
            references=tuple(
                CoachReferencePayload.from_dict(reference) for reference in references
            ),
            coach_telemetry_version=data["coach_telemetry_version"],
        )
