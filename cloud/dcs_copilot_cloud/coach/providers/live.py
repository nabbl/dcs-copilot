"""Permission-gated session store for normalized live Coach observations."""

from __future__ import annotations

from collections.abc import Iterable

from ..capabilities import CapabilityManager, CapabilityTransition
from ..models import OwnshipState, ReferenceObject, ReferenceObjectType, TelemetrySource


class LiveObservationStore:
    def __init__(
        self,
        capabilities: CapabilityManager,
        *,
        ownship_stale_seconds: float = 1.0,
        reference_stale_seconds: float = 1.0,
    ) -> None:
        if ownship_stale_seconds <= 0 or reference_stale_seconds <= 0:
            raise ValueError("observation stale timeouts must be positive")
        self.capabilities = capabilities
        self.ownship_stale_seconds = ownship_stale_seconds
        self.reference_stale_seconds = reference_stale_seconds
        self.ownship: OwnshipState | None = None
        self._references: dict[ReferenceObjectType, ReferenceObject] = {}
        capabilities.add_change_callback(self._capabilities_changed)

    @property
    def references(self) -> tuple[ReferenceObject, ...]:
        return tuple(self._references.values())

    def update_ownship(self, ownship: OwnshipState | None) -> None:
        self.ownship = ownship

    def replace_references(
        self,
        references: Iterable[ReferenceObject],
        *,
        source: TelemetrySource = TelemetrySource.DCS_EXPORT,
    ) -> bool:
        if (
            not self.capabilities.dcs.world_object_export
            or source is not TelemetrySource.DCS_EXPORT
        ):
            self._references.clear()
            return False
        selected: dict[ReferenceObjectType, ReferenceObject] = {}
        for reference in references:
            if reference.source is not TelemetrySource.DCS_EXPORT:
                continue
            selected.setdefault(reference.object_type, reference)
        self._references = selected
        return True

    def get_reference(
        self,
        object_type: ReferenceObjectType,
        *,
        now: float,
    ) -> ReferenceObject | None:
        if not self.capabilities.dcs.world_object_export:
            return None
        return self._references.get(object_type)

    def clear(self) -> None:
        self.ownship = None
        self._references.clear()

    def _capabilities_changed(self, transition: CapabilityTransition) -> None:
        if transition.world_object_export_lost:
            self._references.clear()
