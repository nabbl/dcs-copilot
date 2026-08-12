"""Backend-authoritative raw telemetry store keyed by stable semantic identity."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from ..state.models import TelemetryValue

OutputType = Literal["integer", "string"]


@dataclass(frozen=True, slots=True)
class RawTelemetryKey:
    module: str
    identifier: str
    output_type: OutputType
    output_index: int = 0


@dataclass(slots=True)
class _RawEntry:
    value: int | str
    received_at: float


@dataclass(slots=True)
class _CatalogEntry:
    max_value: int | None = None


class RawTelemetryStore:
    """Bounded, non-persistent store of decoded raw telemetry values.

    Keyed by :class:`RawTelemetryKey`, which is a stable semantic identity
    independent of any DCS-BIOS address-space details. Values are never
    written to disk or any log/database — this is purely an in-memory cache
    used to normalize aircraft state on demand.
    """

    max_controls: int = 4096
    stale_timeout: float = 30.0

    def __init__(
        self,
        *,
        max_controls: int | None = None,
        stale_timeout: float | None = None,
    ) -> None:
        if max_controls is not None:
            self.max_controls = max_controls
        if stale_timeout is not None:
            self.stale_timeout = stale_timeout
        self._entries: OrderedDict[RawTelemetryKey, _RawEntry] = OrderedDict()
        self._catalog: dict[RawTelemetryKey, _CatalogEntry] = {}

    def catalog_register(
        self, key: RawTelemetryKey, *, max_value: int | None = None
    ) -> None:
        """Idempotently register a known control and its optional max_value."""
        existing = self._catalog.get(key)
        if existing is None:
            if len(self._catalog) >= self.max_controls:
                raise ValueError("raw telemetry catalog exceeds the control limit")
            self._catalog[key] = _CatalogEntry(max_value=max_value)
        elif max_value is not None:
            existing.max_value = max_value

    def is_cataloged(self, key: RawTelemetryKey) -> bool:
        return key in self._catalog

    def catalog_max_value(self, key: RawTelemetryKey) -> int | None:
        entry = self._catalog.get(key)
        return entry.max_value if entry is not None else None

    def update(self, key: RawTelemetryKey, value: int | str, *, received_at: float) -> None:
        if key in self._entries:
            self._entries[key] = _RawEntry(value=value, received_at=received_at)
            self._entries.move_to_end(key)
            return
        if len(self._entries) >= self.max_controls:
            self._entries.popitem(last=False)
        self._entries[key] = _RawEntry(value=value, received_at=received_at)

    def mark_unavailable(self, key: RawTelemetryKey) -> None:
        self._entries.pop(key, None)

    def read(self, key: RawTelemetryKey, *, now: float) -> TelemetryValue[int | str]:
        source = f"raw:{key.module}/{key.identifier}"
        entry = self._entries.get(key)
        if entry is None:
            return TelemetryValue.unavailable(source)
        return TelemetryValue(
            value=entry.value,
            available=True,
            updated_at=entry.received_at,
            source=source,
            stale=now - entry.received_at > self.stale_timeout,
        )

    def clear(self) -> None:
        self._entries.clear()

    def reset(self) -> None:
        self._entries.clear()
        self._catalog.clear()

    @property
    def entry_count(self) -> int:
        return len(self._entries)
