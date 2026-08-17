from __future__ import annotations

from dcs_copilot_cloud.coach.capabilities import CapabilityManager, DcsCapabilities
from dcs_copilot_cloud.coach.models import (
    ObservationQuality,
    ReferenceObject,
    ReferenceObjectType,
    TelemetrySource,
)
from dcs_copilot_cloud.coach.providers.live import LiveObservationStore
from dcs_copilot_cloud.coach.spatial import Vec3


def _lead(timestamp: float = 10.0) -> ReferenceObject:
    return ReferenceObject(
        object_id="lead-1",
        object_type=ReferenceObjectType.LEAD_AIRCRAFT,
        position=Vec3(100.0, 200.0, 300.0),
        velocity=Vec3(10.0, 0.0, 20.0),
        heading_deg=45.0,
        timestamp=timestamp,
        source=TelemetrySource.DCS_EXPORT,
        name="Lead",
    )


def test_live_references_are_cleared_immediately_when_permission_is_lost() -> None:
    capabilities = CapabilityManager(
        DcsCapabilities(ownship_export=True, world_object_export=True)
    )
    store = LiveObservationStore(capabilities, reference_stale_seconds=2.0)
    store.replace_references([_lead()])
    assert store.get_reference(ReferenceObjectType.LEAD_AIRCRAFT, now=10.0) is not None

    capabilities.update(DcsCapabilities(ownship_export=True, world_object_export=False))

    assert store.references == ()
    assert store.get_reference(ReferenceObjectType.LEAD_AIRCRAFT, now=10.0) is None


def test_live_tacview_cannot_restore_references_when_dcs_export_is_blocked() -> None:
    capabilities = CapabilityManager(
        DcsCapabilities(ownship_export=True, world_object_export=False)
    )
    store = LiveObservationStore(capabilities)

    assert store.replace_references([_lead()], source=TelemetrySource.TACVIEW) is False
    assert store.references == ()


def test_stale_reference_is_returned_with_stale_quality() -> None:
    capabilities = CapabilityManager(
        DcsCapabilities(ownship_export=True, world_object_export=True)
    )
    store = LiveObservationStore(capabilities, reference_stale_seconds=2.0)
    store.replace_references([_lead(timestamp=10.0)])

    reference = store.get_reference(ReferenceObjectType.LEAD_AIRCRAFT, now=12.1)

    assert reference is not None
    assert reference.quality_at(12.1, stale_after=2.0) is ObservationQuality.STALE
