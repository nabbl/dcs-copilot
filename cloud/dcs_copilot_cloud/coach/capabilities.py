"""Authoritative DCS permissions and centrally derived Coach capabilities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class DcsCapabilities:
    ownship_export: bool = False
    world_object_export: bool = False
    sensor_export: bool = False
    cockpit_state: bool = False


@dataclass(frozen=True, slots=True)
class CoachCapabilities:
    ownship_coaching: bool = False
    formation_coaching: bool = False
    carrier_pattern_coaching: bool = False
    carrier_approach_geometry: bool = False
    procedure_coaching: bool = False

    @classmethod
    def from_dcs(cls, capabilities: DcsCapabilities) -> CoachCapabilities:
        spatial = capabilities.ownship_export and capabilities.world_object_export
        return cls(
            ownship_coaching=capabilities.ownship_export,
            formation_coaching=spatial,
            carrier_pattern_coaching=spatial,
            carrier_approach_geometry=spatial,
            procedure_coaching=capabilities.cockpit_state,
        )


@dataclass(frozen=True, slots=True)
class CapabilityTransition:
    previous_dcs: DcsCapabilities
    current_dcs: DcsCapabilities
    previous_coach: CoachCapabilities
    current_coach: CoachCapabilities

    @property
    def world_object_export_lost(self) -> bool:
        return (
            self.previous_dcs.world_object_export
            and not self.current_dcs.world_object_export
        )


class CapabilityManager:
    """Session-scoped source of truth for all Coach availability decisions."""

    __slots__ = ("_callbacks", "_dcs")

    def __init__(self, capabilities: DcsCapabilities | None = None) -> None:
        self._dcs = capabilities or DcsCapabilities()
        self._callbacks: list[Callable[[CapabilityTransition], None]] = []

    @property
    def dcs(self) -> DcsCapabilities:
        return self._dcs

    @property
    def coach(self) -> CoachCapabilities:
        return CoachCapabilities.from_dcs(self.dcs)

    def status(self) -> dict[str, dict[str, bool]]:
        return {
            "dcs": asdict(self.dcs),
            "coach": asdict(self.coach),
        }

    def add_change_callback(
        self, callback: Callable[[CapabilityTransition], None]
    ) -> None:
        self._callbacks.append(callback)

    def update(self, capabilities: DcsCapabilities) -> CapabilityTransition:
        previous_dcs = self.dcs
        previous_coach = self.coach
        self._dcs = capabilities
        transition = CapabilityTransition(
            previous_dcs,
            capabilities,
            previous_coach,
            self.coach,
        )
        for callback in tuple(self._callbacks):
            callback(transition)
        return transition
