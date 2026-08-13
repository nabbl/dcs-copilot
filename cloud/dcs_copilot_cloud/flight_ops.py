"""Deterministic in-flight phase and departure-cleanup evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .checklists.models import ChecklistItemStatus
from .ground_ops import ReadinessItem, ReadinessReport, ReadinessStatus
from .state.models import (
    AircraftState,
    FlapState,
    FlightPhase,
    GearState,
    TelemetryValue,
)


class FlightOpsStage(StrEnum):
    UNKNOWN = "UNKNOWN"
    DEPARTURE = "DEPARTURE"
    EN_ROUTE = "EN_ROUTE"
    COMBAT = "COMBAT"
    REFUELING = "REFUELING"
    ARRIVAL = "ARRIVAL"


@dataclass(frozen=True, slots=True)
class FlightOpsSnapshot:
    available: bool
    stage: FlightOpsStage
    departure_cleanup: ReadinessReport


class FlightOpsCoordinator:
    """Summarize flight context without asking the LLM to infer semantics."""

    def evaluate(self, state: AircraftState) -> FlightOpsSnapshot:
        if not state.connected or state.flight_phase is FlightPhase.UNKNOWN:
            return FlightOpsSnapshot(
                False,
                FlightOpsStage.UNKNOWN,
                ReadinessReport(ReadinessStatus.UNKNOWN, ()),
            )

        stage = _stage_for_phase(state.flight_phase)
        cleanup = self.departure_cleanup(state)
        return FlightOpsSnapshot(True, stage, cleanup)

    @staticmethod
    def departure_cleanup(state: AircraftState) -> ReadinessReport:
        if not state.connected:
            return ReadinessReport(ReadinessStatus.UNKNOWN, ())
        if state.flight_phase not in {FlightPhase.TAKEOFF, FlightPhase.CLIMB}:
            return ReadinessReport(ReadinessStatus.NOT_APPLICABLE, ())
        if not state.airborne.usable:
            return ReadinessReport(ReadinessStatus.UNKNOWN, ())
        if not state.airborne.value:
            return ReadinessReport(ReadinessStatus.NOT_APPLICABLE, ())

        items = (
            _expected("gear_up", "Landing gear", state.gear_position, GearState.UP),
            _expected("flaps_auto", "Flaps", state.flap_position, FlapState.AUTO),
            _expected(
                "launch_bar_retracted",
                "Launch bar",
                state.launch_bar_deployed,
                False,
            ),
        )
        return _report(items)


def _stage_for_phase(phase: FlightPhase) -> FlightOpsStage:
    if phase in {FlightPhase.TAKEOFF, FlightPhase.CLIMB}:
        return FlightOpsStage.DEPARTURE
    if phase is FlightPhase.CRUISE:
        return FlightOpsStage.EN_ROUTE
    if phase is FlightPhase.COMBAT:
        return FlightOpsStage.COMBAT
    if phase is FlightPhase.REFUELING:
        return FlightOpsStage.REFUELING
    if phase in {FlightPhase.APPROACH, FlightPhase.LANDING}:
        return FlightOpsStage.ARRIVAL
    return FlightOpsStage.UNKNOWN


def _expected(
    item_id: str,
    label: str,
    telemetry: TelemetryValue[Any],
    expected: Any,
) -> ReadinessItem:
    if not telemetry.usable:
        return ReadinessItem(
            item_id,
            label,
            ChecklistItemStatus.UNCONFIRMED,
            expected,
            telemetry.value if telemetry.available else None,
            "telemetry is stale" if telemetry.stale else "telemetry is unavailable",
        )
    passed = telemetry.value == expected
    return ReadinessItem(
        item_id,
        label,
        ChecklistItemStatus.COMPLETE if passed else ChecklistItemStatus.INCOMPLETE,
        expected,
        telemetry.value,
        "verified" if passed else f"expected {expected}, observed {telemetry.value}",
    )


def _report(items: tuple[ReadinessItem, ...]) -> ReadinessReport:
    if any(item.status is ChecklistItemStatus.INCOMPLETE for item in items):
        status = ReadinessStatus.BLOCKED
    elif any(item.status is ChecklistItemStatus.UNCONFIRMED for item in items):
        status = ReadinessStatus.UNKNOWN
    else:
        status = ReadinessStatus.READY
    return ReadinessReport(status, items)


__all__ = ["FlightOpsCoordinator", "FlightOpsSnapshot", "FlightOpsStage"]
