"""Immutable validated telemetry models for protocol version 2."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .messages import ControlMessage, ProtocolError

TELEMETRY_VERSION = 1

_MAX_ENVELOPE_BYTES = 256 * 1024  # 256 KiB
_MAX_MODULE_LENGTH = 64
_MAX_IDENTIFIER_LENGTH = 64
_MAX_DESCRIPTION_LENGTH = 256
_MAX_STRING_VALUE_LENGTH = 256
_MAX_SEQUENCE = 2**53 - 1  # JSON-safe integer maximum
_MAX_AIRCRAFT_LENGTH = 64
_MAX_CHUNK_COUNT = 64
_MAX_ENTRIES = 256
_MAX_SNAPSHOT_VALUES = 1024
_MAX_DELTA_VALUES = 1024

OUTPUT_TYPES = frozenset({"integer", "string"})

_IDENTITY_FIELDS = frozenset({"module", "identifier", "output_type", "output_index"})
_CATALOG_ENTRY_FIELDS = frozenset({"identity", "description", "integer_max", "string_length"})
_DECODED_VALUE_FIELDS = frozenset({"identity", "available", "value", "observed_at_ms"})
_COMMON_PAYLOAD_FIELDS = frozenset(
    {"telemetry_version", "epoch", "sequence", "aircraft", "chunk_index", "chunk_count"}
)


class TelemetryProtocolError(ProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class ControlIdentity:
    """Uniquely identifies a single cockpit control output."""

    module: str
    identifier: str
    output_type: str
    output_index: int

    def __post_init__(self) -> None:
        if not self.module or len(self.module) > _MAX_MODULE_LENGTH:
            raise TelemetryProtocolError(
                f"module must be 1 to {_MAX_MODULE_LENGTH} characters"
            )
        if not self.identifier or len(self.identifier) > _MAX_IDENTIFIER_LENGTH:
            raise TelemetryProtocolError(
                f"identifier must be 1 to {_MAX_IDENTIFIER_LENGTH} characters"
            )
        if self.output_type not in OUTPUT_TYPES:
            raise TelemetryProtocolError(
                f"output_type must be one of: {', '.join(sorted(OUTPUT_TYPES))}"
            )
        if (
            not isinstance(self.output_index, int)
            or isinstance(self.output_index, bool)
            or self.output_index < 0
        ):
            raise TelemetryProtocolError("output_index must be a nonnegative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "identifier": self.identifier,
            "output_type": self.output_type,
            "output_index": self.output_index,
        }

    @classmethod
    def from_dict(cls, data: object) -> ControlIdentity:
        if not isinstance(data, dict):
            raise TelemetryProtocolError("identity must be an object")
        unknown = sorted(data.keys() - _IDENTITY_FIELDS)
        if unknown:
            raise TelemetryProtocolError(
                "identity contains unknown fields: " + ", ".join(unknown)
            )
        missing = sorted(_IDENTITY_FIELDS - data.keys())
        if missing:
            raise TelemetryProtocolError(
                "identity missing fields: " + ", ".join(missing)
            )
        module = data["module"]
        identifier = data["identifier"]
        output_type = data["output_type"]
        output_index = data["output_index"]
        if not isinstance(module, str):
            raise TelemetryProtocolError("module must be a string")
        if not isinstance(identifier, str):
            raise TelemetryProtocolError("identifier must be a string")
        if not isinstance(output_type, str):
            raise TelemetryProtocolError("output_type must be a string")
        if not isinstance(output_index, int) or isinstance(output_index, bool):
            raise TelemetryProtocolError("output_index must be an integer")
        return cls(module, identifier, output_type, output_index)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Describes a single telemetry output — never includes address/mask/shift/filesystem data."""

    identity: ControlIdentity
    description: str
    integer_max: int | None = None
    string_length: int | None = None

    def __post_init__(self) -> None:
        if not self.description or len(self.description) > _MAX_DESCRIPTION_LENGTH:
            raise TelemetryProtocolError(
                f"description must be 1 to {_MAX_DESCRIPTION_LENGTH} characters"
            )
        if self.identity.output_type == "integer":
            if (
                not isinstance(self.integer_max, int)
                or isinstance(self.integer_max, bool)
                or self.integer_max < 0
            ):
                raise TelemetryProtocolError(
                    "integer entries require a nonnegative integer_max"
                )
            if self.string_length is not None:
                raise TelemetryProtocolError(
                    "integer entries must not include string_length"
                )
        elif self.identity.output_type == "string":
            if (
                not isinstance(self.string_length, int)
                or isinstance(self.string_length, bool)
                or self.string_length <= 0
                or self.string_length > _MAX_STRING_VALUE_LENGTH
            ):
                raise TelemetryProtocolError(
                    f"string entries require a positive bounded string_length"
                    f" (1..{_MAX_STRING_VALUE_LENGTH})"
                )
            if self.integer_max is not None:
                raise TelemetryProtocolError(
                    "string entries must not include integer_max"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialise — address, mask, shift, and filesystem data are never included."""
        d: dict[str, Any] = {
            "identity": self.identity.to_dict(),
            "description": self.description,
        }
        if self.integer_max is not None:
            d["integer_max"] = self.integer_max
        if self.string_length is not None:
            d["string_length"] = self.string_length
        return d

    @classmethod
    def from_dict(cls, data: object) -> CatalogEntry:
        if not isinstance(data, dict):
            raise TelemetryProtocolError("catalog entry must be an object")
        unknown = sorted(data.keys() - _CATALOG_ENTRY_FIELDS)
        if unknown:
            raise TelemetryProtocolError(
                "catalog entry contains unknown fields: " + ", ".join(unknown)
            )
        if "identity" not in data or "description" not in data:
            missing = sorted({"identity", "description"} - data.keys())
            raise TelemetryProtocolError(
                "catalog entry missing fields: " + ", ".join(missing)
            )
        identity = ControlIdentity.from_dict(data["identity"])
        description = data["description"]
        integer_max = data.get("integer_max")
        string_length = data.get("string_length")
        if not isinstance(description, str):
            raise TelemetryProtocolError("description must be a string")
        if integer_max is not None and (
            not isinstance(integer_max, int) or isinstance(integer_max, bool)
        ):
            raise TelemetryProtocolError("integer_max must be an integer")
        if string_length is not None and (
            not isinstance(string_length, int) or isinstance(string_length, bool)
        ):
            raise TelemetryProtocolError("string_length must be an integer")
        return cls(identity, description, integer_max, string_length)


@dataclass(frozen=True, slots=True)
class DecodedValue:
    """A single resolved telemetry value — available or not."""

    identity: ControlIdentity
    available: bool
    value: int | str | None = None
    observed_at_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.available:
            if self.value is not None:
                raise TelemetryProtocolError(
                    "unavailable decoded values must have value=None"
                )
        else:
            if self.identity.output_type == "integer":
                if not isinstance(self.value, int) or isinstance(self.value, bool):
                    raise TelemetryProtocolError(
                        "available integer values must be integers (not bool)"
                    )
            elif self.identity.output_type == "string":
                if not isinstance(self.value, str):
                    raise TelemetryProtocolError(
                        "available string values must be strings"
                    )
                if len(self.value) > _MAX_STRING_VALUE_LENGTH:
                    raise TelemetryProtocolError(
                        f"string value may not exceed {_MAX_STRING_VALUE_LENGTH} characters"
                    )
        if self.observed_at_ms is not None and (
            not isinstance(self.observed_at_ms, int)
            or isinstance(self.observed_at_ms, bool)
            or self.observed_at_ms < 0
        ):
            raise TelemetryProtocolError(
                "observed_at_ms must be a nonnegative integer or null"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "identity": self.identity.to_dict(),
            "available": self.available,
            "value": self.value,
        }
        if self.observed_at_ms is not None:
            d["observed_at_ms"] = self.observed_at_ms
        return d

    @classmethod
    def from_dict(cls, data: object) -> DecodedValue:
        if not isinstance(data, dict):
            raise TelemetryProtocolError("decoded value must be an object")
        unknown = sorted(data.keys() - _DECODED_VALUE_FIELDS)
        if unknown:
            raise TelemetryProtocolError(
                "decoded value contains unknown fields: " + ", ".join(unknown)
            )
        for required in ("identity", "available", "value"):
            if required not in data:
                raise TelemetryProtocolError(f"decoded value missing '{required}'")
        identity = ControlIdentity.from_dict(data["identity"])
        available = data["available"]
        value = data["value"]
        observed_at_ms = data.get("observed_at_ms")
        if not isinstance(available, bool):
            raise TelemetryProtocolError("available must be a boolean")
        if value is not None and isinstance(value, bool):
            raise TelemetryProtocolError("value must not be a boolean")
        if observed_at_ms is not None and (
            not isinstance(observed_at_ms, int) or isinstance(observed_at_ms, bool)
        ):
            raise TelemetryProtocolError("observed_at_ms must be an integer or null")
        return cls(identity, available, value, observed_at_ms)


def _check_unique_identities(items: list[Any]) -> None:
    seen: set[tuple[str, str, str, int]] = set()
    for item in items:
        ident = item.identity
        key = (ident.module, ident.identifier, ident.output_type, ident.output_index)
        if key in seen:
            raise TelemetryProtocolError(
                f"duplicate identity in message: "
                f"{ident.module}/{ident.identifier}[{ident.output_index}]"
            )
        seen.add(key)


def _validate_epoch(epoch: object) -> str:
    if not isinstance(epoch, str):
        raise TelemetryProtocolError("epoch must be a string")
    try:
        UUID(epoch)
    except (ValueError, TypeError) as exc:
        raise TelemetryProtocolError("epoch must be a valid UUID string") from exc
    return epoch


def _validate_common_fields(
    payload: dict[str, Any],
) -> tuple[str, int, str, int, int, int]:
    """Return (epoch, sequence, aircraft, chunk_index, chunk_count, telemetry_version)."""
    epoch = _validate_epoch(payload.get("epoch"))
    sequence = payload.get("sequence")
    aircraft = payload.get("aircraft")
    chunk_index = payload.get("chunk_index")
    chunk_count = payload.get("chunk_count")
    telemetry_version = payload.get("telemetry_version")

    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 0
        or sequence > _MAX_SEQUENCE
    ):
        raise TelemetryProtocolError(
            f"sequence must be a nonnegative integer not exceeding {_MAX_SEQUENCE}"
        )
    if not isinstance(aircraft, str) or not aircraft or len(aircraft) > _MAX_AIRCRAFT_LENGTH:
        raise TelemetryProtocolError(
            f"aircraft must be 1 to {_MAX_AIRCRAFT_LENGTH} characters"
        )
    if (
        not isinstance(chunk_index, int)
        or isinstance(chunk_index, bool)
        or chunk_index < 0
    ):
        raise TelemetryProtocolError("chunk_index must be a nonnegative integer")
    if (
        not isinstance(chunk_count, int)
        or isinstance(chunk_count, bool)
        or chunk_count <= 0
        or chunk_count > _MAX_CHUNK_COUNT
    ):
        raise TelemetryProtocolError(
            f"chunk_count must be 1 to {_MAX_CHUNK_COUNT}"
        )
    if chunk_index >= chunk_count:
        raise TelemetryProtocolError("chunk_index must be less than chunk_count")
    if (
        not isinstance(telemetry_version, int)
        or isinstance(telemetry_version, bool)
        or telemetry_version != TELEMETRY_VERSION
    ):
        raise TelemetryProtocolError(
            f"unsupported telemetry schema version {telemetry_version!r}"
        )
    return epoch, sequence, aircraft, chunk_index, chunk_count, telemetry_version


def _enforce_payload_size(message: ControlMessage) -> None:
    encoded = json.dumps(message.payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise TelemetryProtocolError(
            f"telemetry payload exceeds {_MAX_ENVELOPE_BYTES // 1024} KiB limit"
        )


def _check_exact_fields(payload: dict[str, Any], expected: frozenset[str]) -> None:
    unknown = sorted(payload.keys() - expected)
    missing = sorted(expected - payload.keys())
    if missing:
        raise TelemetryProtocolError("missing fields: " + ", ".join(missing))
    if unknown:
        raise TelemetryProtocolError("unknown fields: " + ", ".join(unknown))


@dataclass(frozen=True, slots=True)
class TelemetryCatalog:
    """A (possibly chunked) catalog of all telemetry outputs for an aircraft session."""

    epoch: str
    sequence: int
    aircraft: str
    chunk_index: int
    chunk_count: int
    entries: list[CatalogEntry]
    telemetry_version: int = TELEMETRY_VERSION

    def __post_init__(self) -> None:
        _validate_epoch(self.epoch)
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
            or self.sequence > _MAX_SEQUENCE
        ):
            raise TelemetryProtocolError("sequence out of bounds")
        if not self.aircraft or len(self.aircraft) > _MAX_AIRCRAFT_LENGTH:
            raise TelemetryProtocolError(
                f"aircraft must be 1 to {_MAX_AIRCRAFT_LENGTH} characters"
            )
        if (
            not isinstance(self.chunk_index, int)
            or isinstance(self.chunk_index, bool)
            or self.chunk_index < 0
        ):
            raise TelemetryProtocolError("chunk_index must be a nonnegative integer")
        if (
            not isinstance(self.chunk_count, int)
            or isinstance(self.chunk_count, bool)
            or self.chunk_count <= 0
            or self.chunk_count > _MAX_CHUNK_COUNT
        ):
            raise TelemetryProtocolError(f"chunk_count must be 1 to {_MAX_CHUNK_COUNT}")
        if self.chunk_index >= self.chunk_count:
            raise TelemetryProtocolError("chunk_index must be less than chunk_count")
        if len(self.entries) > _MAX_ENTRIES:
            raise TelemetryProtocolError(f"entries may not exceed {_MAX_ENTRIES}")
        _check_unique_identities(self.entries)
        object.__setattr__(self, "entries", list(self.entries))

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "telemetry.catalog",
            {
                "telemetry_version": self.telemetry_version,
                "epoch": self.epoch,
                "sequence": self.sequence,
                "aircraft": self.aircraft,
                "chunk_index": self.chunk_index,
                "chunk_count": self.chunk_count,
                "entries": [e.to_dict() for e in self.entries],
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> TelemetryCatalog:
        if message.type != "telemetry.catalog":
            raise TelemetryProtocolError("expected telemetry.catalog")
        _enforce_payload_size(message)
        _check_exact_fields(message.payload, _COMMON_PAYLOAD_FIELDS | {"entries"})
        epoch, sequence, aircraft, chunk_index, chunk_count, version = (
            _validate_common_fields(message.payload)
        )
        raw_entries = message.payload["entries"]
        if not isinstance(raw_entries, list):
            raise TelemetryProtocolError("entries must be an array")
        if len(raw_entries) > _MAX_ENTRIES:
            raise TelemetryProtocolError(f"entries may not exceed {_MAX_ENTRIES}")
        entries = [CatalogEntry.from_dict(e) for e in raw_entries]
        _check_unique_identities(entries)
        return cls(epoch, sequence, aircraft, chunk_index, chunk_count, entries, version)


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """A complete snapshot of all telemetry values at a single point in time."""

    epoch: str
    sequence: int
    aircraft: str
    chunk_index: int
    chunk_count: int
    values: list[DecodedValue]
    telemetry_version: int = TELEMETRY_VERSION

    def __post_init__(self) -> None:
        _validate_epoch(self.epoch)
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
            or self.sequence > _MAX_SEQUENCE
        ):
            raise TelemetryProtocolError("sequence out of bounds")
        if not self.aircraft or len(self.aircraft) > _MAX_AIRCRAFT_LENGTH:
            raise TelemetryProtocolError(
                f"aircraft must be 1 to {_MAX_AIRCRAFT_LENGTH} characters"
            )
        if (
            not isinstance(self.chunk_index, int)
            or isinstance(self.chunk_index, bool)
            or self.chunk_index < 0
        ):
            raise TelemetryProtocolError("chunk_index must be a nonnegative integer")
        if (
            not isinstance(self.chunk_count, int)
            or isinstance(self.chunk_count, bool)
            or self.chunk_count <= 0
            or self.chunk_count > _MAX_CHUNK_COUNT
        ):
            raise TelemetryProtocolError(f"chunk_count must be 1 to {_MAX_CHUNK_COUNT}")
        if self.chunk_index >= self.chunk_count:
            raise TelemetryProtocolError("chunk_index must be less than chunk_count")
        if len(self.values) > _MAX_SNAPSHOT_VALUES:
            raise TelemetryProtocolError(
                f"snapshot values may not exceed {_MAX_SNAPSHOT_VALUES}"
            )
        _check_unique_identities(self.values)
        object.__setattr__(self, "values", list(self.values))

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "telemetry.snapshot",
            {
                "telemetry_version": self.telemetry_version,
                "epoch": self.epoch,
                "sequence": self.sequence,
                "aircraft": self.aircraft,
                "chunk_index": self.chunk_index,
                "chunk_count": self.chunk_count,
                "values": [v.to_dict() for v in self.values],
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> TelemetrySnapshot:
        if message.type != "telemetry.snapshot":
            raise TelemetryProtocolError("expected telemetry.snapshot")
        _enforce_payload_size(message)
        _check_exact_fields(message.payload, _COMMON_PAYLOAD_FIELDS | {"values"})
        epoch, sequence, aircraft, chunk_index, chunk_count, version = (
            _validate_common_fields(message.payload)
        )
        raw_values = message.payload["values"]
        if not isinstance(raw_values, list):
            raise TelemetryProtocolError("values must be an array")
        if len(raw_values) > _MAX_SNAPSHOT_VALUES:
            raise TelemetryProtocolError(
                f"snapshot values may not exceed {_MAX_SNAPSHOT_VALUES}"
            )
        values = [DecodedValue.from_dict(v) for v in raw_values]
        _check_unique_identities(values)
        return cls(epoch, sequence, aircraft, chunk_index, chunk_count, values, version)


@dataclass(frozen=True, slots=True)
class TelemetryDelta:
    """Changed telemetry values since the last snapshot or delta."""

    epoch: str
    sequence: int
    aircraft: str
    chunk_index: int
    chunk_count: int
    values: list[DecodedValue]
    telemetry_version: int = TELEMETRY_VERSION

    def __post_init__(self) -> None:
        _validate_epoch(self.epoch)
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
            or self.sequence > _MAX_SEQUENCE
        ):
            raise TelemetryProtocolError("sequence out of bounds")
        if not self.aircraft or len(self.aircraft) > _MAX_AIRCRAFT_LENGTH:
            raise TelemetryProtocolError(
                f"aircraft must be 1 to {_MAX_AIRCRAFT_LENGTH} characters"
            )
        if (
            not isinstance(self.chunk_index, int)
            or isinstance(self.chunk_index, bool)
            or self.chunk_index < 0
        ):
            raise TelemetryProtocolError("chunk_index must be a nonnegative integer")
        if (
            not isinstance(self.chunk_count, int)
            or isinstance(self.chunk_count, bool)
            or self.chunk_count <= 0
            or self.chunk_count > _MAX_CHUNK_COUNT
        ):
            raise TelemetryProtocolError(f"chunk_count must be 1 to {_MAX_CHUNK_COUNT}")
        if self.chunk_index >= self.chunk_count:
            raise TelemetryProtocolError("chunk_index must be less than chunk_count")
        if not self.values or len(self.values) > _MAX_DELTA_VALUES:
            raise TelemetryProtocolError(
                f"delta values must be 1 to {_MAX_DELTA_VALUES}"
            )
        _check_unique_identities(self.values)
        object.__setattr__(self, "values", list(self.values))

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "telemetry.delta",
            {
                "telemetry_version": self.telemetry_version,
                "epoch": self.epoch,
                "sequence": self.sequence,
                "aircraft": self.aircraft,
                "chunk_index": self.chunk_index,
                "chunk_count": self.chunk_count,
                "values": [v.to_dict() for v in self.values],
            },
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> TelemetryDelta:
        if message.type != "telemetry.delta":
            raise TelemetryProtocolError("expected telemetry.delta")
        _enforce_payload_size(message)
        _check_exact_fields(message.payload, _COMMON_PAYLOAD_FIELDS | {"values"})
        epoch, sequence, aircraft, chunk_index, chunk_count, version = (
            _validate_common_fields(message.payload)
        )
        raw_values = message.payload["values"]
        if not isinstance(raw_values, list):
            raise TelemetryProtocolError("values must be an array")
        if not raw_values:
            raise TelemetryProtocolError("delta values must contain at least one entry")
        if len(raw_values) > _MAX_DELTA_VALUES:
            raise TelemetryProtocolError(
                f"delta values may not exceed {_MAX_DELTA_VALUES}"
            )
        values = [DecodedValue.from_dict(v) for v in raw_values]
        _check_unique_identities(values)
        return cls(epoch, sequence, aircraft, chunk_index, chunk_count, values, version)
