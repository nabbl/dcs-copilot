"""Aircraft-independent normalization from the DCS-BIOS CommonData module."""

from __future__ import annotations

from typing import Any

from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import PartialAircraftState, TelemetryValue

from .base import ControlReader, combine_values


class GenericAircraftAdapter:
    def __init__(self, registry: DcsBiosControlRegistry) -> None:
        self.aircraft_names: set[str] = set()
        self.registry = registry
        self._last_model_time: int | None = None
        self._last_model_time_advance_at: float | None = None
        self._common_data_validated = False
        self.health_timeout = 2.0

    def normalize(
        self,
        bios_state: DcsBiosState,
        *,
        now: float,
        stale_timeout: float,
    ) -> PartialAircraftState:
        reader = ControlReader(
            self.registry, bios_state, now=now, stale_timeout=stale_timeout
        )
        time_high = reader.read("CommonData", "TIME_MODEL_HIGH", output_type="integer")
        time_low = reader.read("CommonData", "TIME_MODEL_LOW", output_type="integer")
        model_time = combine_values(
            [time_high, time_low],
            int(time_high.value) * 65536 + int(time_low.value)
            if time_high.usable
            and time_low.usable
            and time_high.value is not None
            and time_low.value is not None
            else None,
            "DCS-BIOS:CommonData/model-time-composite",
        )
        common_data_healthy = self._observe_model_time(model_time, now=now)
        decoded = {
            "indicated_airspeed": reader.read(
                "CommonData",
                "IAS_US_INT",
                lambda value: float(value),
                output_type="integer",
            ),
            "altitude_msl": reader.read(
                "CommonData",
                "ALT_MSL_FT",
                lambda value: float(value),
                output_type="integer",
            ),
            "heading": reader.read(
                "CommonData",
                "HDG_DEG_MAG",
                lambda value: float(value),
                output_type="integer",
            ),
        }
        values = (
            decoded
            if common_data_healthy
            else {
                key: TelemetryValue.unavailable(value.source)
                for key, value in decoded.items()
            }
        )
        raw: dict[str, TelemetryValue[Any]] = {
            key: value for key, value in decoded.items()
        }
        raw["model_time"] = model_time
        return PartialAircraftState(values=values, raw=raw)

    def _observe_model_time(
        self, model_time: TelemetryValue[int], *, now: float
    ) -> bool:
        if not model_time.usable or model_time.value is None:
            self._common_data_validated = False
            return False
        current = int(model_time.value)
        if self._last_model_time is None or current < self._last_model_time:
            self._common_data_validated = False
        elif current > self._last_model_time:
            self._common_data_validated = True
            self._last_model_time_advance_at = now
        self._last_model_time = current
        return bool(
            self._common_data_validated
            and self._last_model_time_advance_at is not None
            and now - self._last_model_time_advance_at <= self.health_timeout
        )
