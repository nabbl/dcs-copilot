"""Cloud ingress for validated normalized Coach telemetry."""

from __future__ import annotations

from dcs_copilot_protocol import CoachTelemetry

from .capabilities import DcsCapabilities
from .coordinator import CoachCoordinator
from .exercises.base import CoachFeedback
from .models import (
    ObservedValue,
    OwnshipState,
    ReferenceObject,
    ReferenceObjectType,
    TelemetrySource,
)
from .spatial import Vec3


class CoachTelemetryIngress:
    def __init__(self, coordinator: CoachCoordinator) -> None:
        self.coordinator = coordinator
        self.last_sequence: int | None = None
        self.last_observed_at_ms: int | None = None

    def accept(
        self, message: CoachTelemetry, *, received_at: float
    ) -> tuple[CoachFeedback, ...]:
        if (
            self.last_observed_at_ms is not None
            and message.observed_at_ms < self.last_observed_at_ms
            and self.last_sequence is not None
            and message.sequence <= self.last_sequence
        ):
            return ()
        self.last_sequence = message.sequence
        self.last_observed_at_ms = message.observed_at_ms
        payload = message.capabilities
        self.coordinator.update_capabilities(
            DcsCapabilities(
                ownship_export=payload.ownship_export,
                world_object_export=payload.world_object_export,
                sensor_export=payload.sensor_export,
                cockpit_state=payload.cockpit_state,
            )
        )
        if message.ownship is None:
            self.coordinator.observations.update_ownship(None)
            return ()
        ownship = _ownship(message.ownship, received_at)
        references = [_reference(value, received_at) for value in message.references]
        return self.coordinator.ingest(ownship, references, now=received_at)

    def reset(self) -> None:
        self.last_sequence = None
        self.last_observed_at_ms = None
        self.coordinator.reset()


def _observed(value, timestamp: float):
    return (
        ObservedValue.observed(
            value,
            source=TelemetrySource.DCS_EXPORT,
            timestamp=timestamp,
        )
        if value is not None
        else ObservedValue()
    )


def _vec(value) -> Vec3 | None:
    return Vec3(value.x, value.y, value.z) if value is not None else None


def _ownship(value, timestamp: float) -> OwnshipState:
    return OwnshipState(
        position=_observed(_vec(value.position), timestamp),
        velocity=_observed(_vec(value.velocity), timestamp),
        heading_deg=_observed(value.heading_deg, timestamp),
        pitch_deg=_observed(value.pitch_deg, timestamp),
        roll_deg=_observed(value.roll_deg, timestamp),
        altitude_msl_ft=_observed(value.altitude_msl_ft, timestamp),
        altitude_agl_ft=_observed(value.altitude_agl_ft, timestamp),
        indicated_airspeed_kt=_observed(value.indicated_airspeed_kt, timestamp),
        vertical_speed_fpm=_observed(value.vertical_speed_fpm, timestamp),
        aoa_deg=_observed(value.aoa_deg, timestamp),
        g_force=_observed(value.g_force, timestamp),
        gear_down=_observed(value.gear_down, timestamp),
        timestamp=timestamp,
    )


def _reference(value, timestamp: float) -> ReferenceObject:
    position = _vec(value.position)
    assert position is not None
    return ReferenceObject(
        object_id=value.object_id,
        object_type=ReferenceObjectType(value.object_type),
        position=position,
        velocity=_vec(value.velocity),
        heading_deg=value.heading_deg,
        pitch_deg=value.pitch_deg,
        roll_deg=value.roll_deg,
        name=value.name,
        timestamp=timestamp,
        source=TelemetrySource.DCS_EXPORT,
    )
