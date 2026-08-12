"""Aircraft-independent normalization from the CommonData module."""

from __future__ import annotations

import math
from typing import Any

from ..state.models import PartialAircraftState, TelemetryValue
from .base import ControlReader, combine_values
from .raw import RawTelemetryStore


class GenericAircraftAdapter:
    def __init__(self) -> None:
        self.aircraft_names: set[str] = set()
        self._last_model_time: int | None = None
        self._last_model_time_advance_at: float | None = None
        self._common_data_validated = False
        self._previous_position: tuple[int, float, float] | None = None
        self.health_timeout = 2.0

    def normalize(
        self,
        raw: RawTelemetryStore,
        *,
        now: float,
    ) -> PartialAircraftState:
        reader = ControlReader(raw, now=now)
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
            "derived:CommonData/model-time-composite",
        )
        common_data_healthy = self._observe_model_time(model_time, now=now)
        latitude = self._read_coordinate(reader, "LAT", negative_direction="S")
        longitude = self._read_coordinate(reader, "LON", negative_direction="W")
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
            "ground_speed": self._ground_speed(
                model_time,
                latitude,
                longitude,
                common_data_healthy=common_data_healthy,
                now=now,
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
        raw_values: dict[str, TelemetryValue[Any]] = {
            key: value for key, value in decoded.items()
        }
        raw_values["model_time"] = model_time
        return PartialAircraftState(values=values, raw=raw_values)

    @staticmethod
    def _read_coordinate(
        reader: ControlReader,
        prefix: str,
        *,
        negative_direction: str,
    ) -> float | None:
        degrees = reader.read(
            "CommonData", f"{prefix}_DEG", output_type="integer"
        )
        minutes = reader.read(
            "CommonData", f"{prefix}_SEC", output_type="integer"
        )
        fractional_minutes = reader.read(
            "CommonData", f"{prefix}_SEC_FRAC", output_type="integer"
        )
        direction = reader.read(
            "CommonData", f"{prefix}_Z_DIR", output_type="string"
        )
        parts = (degrees, minutes, fractional_minutes, direction)
        if any(not part.usable or part.value is None for part in parts):
            return None
        direction_value = str(direction.value).strip().upper()
        valid_directions = {"N", "S"} if prefix == "LAT" else {"E", "W"}
        if direction_value not in valid_directions:
            return None
        value = (
            float(degrees.value)
            + (
                float(minutes.value)
                + float(fractional_minutes.value) / 65535.0
            )
            / 60.0
        )
        return -value if direction_value == negative_direction else value

    def _ground_speed(
        self,
        model_time: TelemetryValue[int],
        latitude: float | None,
        longitude: float | None,
        *,
        common_data_healthy: bool,
        now: float,
    ) -> TelemetryValue[float]:
        source = "derived:CommonData/position-delta"
        if (
            not common_data_healthy
            or not model_time.usable
            or model_time.value is None
            or latitude is None
            or longitude is None
        ):
            self._previous_position = None
            return TelemetryValue.unavailable(source)
        current = (int(model_time.value), latitude, longitude)
        previous = self._previous_position
        self._previous_position = current
        if previous is None or current[0] <= previous[0]:
            return TelemetryValue.unavailable(source)
        elapsed_seconds = (current[0] - previous[0]) / 100.0
        distance_meters = self._great_circle_distance(
            previous[1], previous[2], latitude, longitude
        )
        speed_knots = distance_meters / elapsed_seconds * 1.94384449
        if speed_knots > 2_000:
            return TelemetryValue.unavailable(source)
        return TelemetryValue(
            value=speed_knots,
            available=True,
            updated_at=now,
            source=source,
        )

    @staticmethod
    def _great_circle_distance(
        latitude_a: float,
        longitude_a: float,
        latitude_b: float,
        longitude_b: float,
    ) -> float:
        lat_a = math.radians(latitude_a)
        lat_b = math.radians(latitude_b)
        delta_lat = lat_b - lat_a
        delta_lon = math.radians(longitude_b - longitude_a)
        haversine = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
        )
        return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(haversine)))

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
