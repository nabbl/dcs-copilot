"""Aircraft adapter protocol and symbolic control reader."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from dcs_copilot.dcs.bios_registry import ControlOutputType, DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import PartialAircraftState, TelemetryValue

T = TypeVar("T")


class AircraftAdapter(Protocol):
    aircraft_names: set[str]

    def normalize(
        self,
        bios_state: DcsBiosState,
        *,
        now: float,
        stale_timeout: float,
    ) -> PartialAircraftState: ...


class ControlReader:
    def __init__(
        self,
        registry: DcsBiosControlRegistry,
        bios_state: DcsBiosState,
        *,
        now: float,
        stale_timeout: float,
    ) -> None:
        self.registry = registry
        self.bios_state = bios_state
        self.now = now
        self.stale_timeout = stale_timeout

    def read(
        self,
        module: str,
        identifier: str,
        transform: Callable[[int | str], T | None] | None = None,
        *,
        output_type: ControlOutputType | None = None,
    ) -> TelemetryValue[T | int | str]:
        definition = self.registry.resolve(
            identifier, module=module, output_type=output_type
        )
        source = f"DCS-BIOS:{module}/{identifier}"
        if definition is None:
            return TelemetryValue.unavailable(source)
        raw = self.registry.decode(definition, self.bios_state)
        updated_at = self.bios_state.updated_at(
            definition.address, definition.byte_length
        )
        if raw is None or updated_at is None:
            return TelemetryValue.unavailable(source)
        value: Any = transform(raw) if transform is not None else raw
        if value is None:
            return TelemetryValue.unavailable(source)
        return TelemetryValue(
            value=value,
            available=True,
            updated_at=updated_at,
            source=source,
            stale=self.now - updated_at > self.stale_timeout,
        )

    def fraction(self, module: str, identifier: str) -> TelemetryValue[float]:
        definition = self.registry.resolve(
            identifier, module=module, output_type="integer"
        )
        source = f"DCS-BIOS:{module}/{identifier}"
        if definition is None or not definition.max_value:
            return TelemetryValue.unavailable(source)
        max_value = definition.max_value
        result = self.read(
            module,
            identifier,
            lambda value: float(value) / max_value if isinstance(value, int) else None,
            output_type="integer",
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
