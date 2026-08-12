"""Aircraft adapter protocol and symbolic control reader (backend-authoritative)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from ..state.models import PartialAircraftState, TelemetryValue
from .raw import OutputType, RawTelemetryKey, RawTelemetryStore

T = TypeVar("T")


class AircraftAdapter(Protocol):
    aircraft_names: set[str]

    def normalize(
        self,
        raw: RawTelemetryStore,
        *,
        now: float,
    ) -> PartialAircraftState: ...


class ControlReader:
    def __init__(self, raw: RawTelemetryStore, *, now: float) -> None:
        self.raw = raw
        self.now = now

    def read(
        self,
        module: str,
        identifier: str,
        transform: Callable[[int | str], T | None] | None = None,
        *,
        output_type: OutputType = "integer",
        output_index: int = 0,
    ) -> TelemetryValue[T | int | str]:
        key = RawTelemetryKey(module, identifier, output_type, output_index)
        result = self.raw.read(key, now=self.now)
        source = result.source or f"raw:{module}/{identifier}"
        if not result.available or result.value is None:
            return TelemetryValue.unavailable(source)
        value: Any = transform(result.value) if transform is not None else result.value
        if value is None:
            return TelemetryValue.unavailable(source)
        return TelemetryValue(
            value=value,
            available=True,
            updated_at=result.updated_at,
            source=source,
            stale=result.stale,
        )

    def fraction(
        self, module: str, identifier: str, *, output_index: int = 0
    ) -> TelemetryValue[float]:
        key = RawTelemetryKey(module, identifier, "integer", output_index)
        source = f"raw:{module}/{identifier}"
        max_value = self.raw.catalog_max_value(key)
        if not self.raw.is_cataloged(key) or not max_value:
            return TelemetryValue.unavailable(source)
        result = self.read(
            module,
            identifier,
            lambda value: float(value) / max_value if isinstance(value, int) else None,
            output_type="integer",
            output_index=output_index,
        )
        return TelemetryValue(
            value=float(result.value) if result.value is not None else None,
            available=result.available,
            updated_at=result.updated_at,
            source=result.source,
            stale=result.stale,
        )


def parse_number(value: int | str) -> float | None:
    if isinstance(value, int):
        return float(value)
    normalized = value.strip().replace(",", "")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def map_value(mapping: dict[int, T]) -> Callable[[int | str], T | None]:
    def transform(value: int | str) -> T | None:
        return mapping.get(value) if isinstance(value, int) else None

    return transform


def combine_values(
    values: list[TelemetryValue[Any]], value: T | None, source: str
) -> TelemetryValue[T]:
    if not values or any(not item.available for item in values) or value is None:
        return TelemetryValue.unavailable(source)
    timestamps = [item.updated_at for item in values if item.updated_at is not None]
    return TelemetryValue(
        value=value,
        available=True,
        updated_at=min(timestamps) if timestamps else None,
        source=source,
        stale=any(item.stale for item in values),
    )
