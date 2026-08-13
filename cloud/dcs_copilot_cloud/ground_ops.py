"""Deterministic ground-operations phase and readiness evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .checklists.engine import ChecklistEngine
from .checklists.models import ChecklistItemResult, ChecklistItemStatus
from .state.history import StateHistory
from .state.models import (
    AircraftState,
    CanopyState,
    FlapState,
    FlightPhase,
    GearState,
    MasterArmState,
    TelemetryValue,
)


class GroundOpsPhase(StrEnum):
    UNKNOWN = "UNKNOWN"
    COLD_START = "COLD_START"
    ENGINE_START = "ENGINE_START"
    PRE_TAXI = "PRE_TAXI"
    READY_FOR_TAXI = "READY_FOR_TAXI"
    TAXI = "TAXI"
    CARRIER_LAUNCH = "CARRIER_LAUNCH"
    TAKEOFF_ROLL = "TAKEOFF_ROLL"
    IN_FLIGHT = "IN_FLIGHT"
    POST_LANDING = "POST_LANDING"


class ReadinessStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TakeoffOperation(StrEnum):
    AUTO = "AUTO"
    LAND = "LAND"
    CARRIER = "CARRIER"
    UNKNOWN = "UNKNOWN"


class LineupState(StrEnum):
    UNCONFIRMED = "UNCONFIRMED"
    CARRIER_CONFIRMED = "CARRIER_CONFIRMED"
    TAKEOFF_ROLL = "TAKEOFF_ROLL"


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    id: str
    label: str
    status: ChecklistItemStatus
    expected: Any | None
    actual: Any | None
    reason: str


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: ReadinessStatus
    items: tuple[ReadinessItem, ...]

    @property
    def blocking_items(self) -> tuple[ReadinessItem, ...]:
        return tuple(
            item for item in self.items if item.status is ChecklistItemStatus.INCOMPLETE
        )

    @property
    def unknown_items(self) -> tuple[ReadinessItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.status is ChecklistItemStatus.UNCONFIRMED
        )


@dataclass(frozen=True, slots=True)
class GroundOpsSnapshot:
    available: bool
    phase: GroundOpsPhase
    lineup_state: LineupState
    takeoff_operation: TakeoffOperation
    before_taxi: ReadinessReport
    takeoff: ReadinessReport


class GroundOpsCoordinator:
    """Keep physical ground phase separate from deterministic readiness gates."""

    def evaluate(
        self,
        state: AircraftState,
        history: StateHistory,
        checklist: ChecklistEngine,
        *,
        now: float,
        operation: TakeoffOperation = TakeoffOperation.AUTO,
    ) -> GroundOpsSnapshot:
        if not state.connected or not state.weight_on_wheels.usable:
            unavailable = ReadinessReport(ReadinessStatus.UNKNOWN, ())
            return GroundOpsSnapshot(
                False,
                GroundOpsPhase.UNKNOWN,
                LineupState.UNCONFIRMED,
                TakeoffOperation.UNKNOWN,
                unavailable,
                unavailable,
            )

        before_taxi = self._before_taxi(state, history, checklist, now=now)
        selected_operation = self.resolve_operation(state, operation)
        takeoff = self.takeoff_readiness(state, checklist, operation=operation)
        phase, lineup = self._phase(state, before_taxi)
        return GroundOpsSnapshot(
            True,
            phase,
            lineup,
            selected_operation,
            before_taxi,
            takeoff,
        )

    def takeoff_readiness(
        self,
        state: AircraftState,
        checklist: ChecklistEngine,
        *,
        operation: TakeoffOperation = TakeoffOperation.AUTO,
    ) -> ReadinessReport:
        if not state.connected:
            return ReadinessReport(ReadinessStatus.UNKNOWN, ())
        if state.weight_on_wheels.usable and not bool(state.weight_on_wheels.value):
            return ReadinessReport(ReadinessStatus.NOT_APPLICABLE, ())

        selected_operation = self.resolve_operation(state, operation)
        items = [
            _expected("flaps_half", "Flaps", state.flap_position, FlapState.HALF),
            _expected("gear_down", "Landing gear", state.gear_position, GearState.DOWN),
            _expected("hook_up", "Hook", state.hook_position, False),
            _maximum("speedbrake_retracted", "Speedbrake", state.speed_brake, 0.05),
            _expected(
                "master_arm_safe_takeoff",
                "Master Arm",
                state.master_arm,
                MasterArmState.SAFE,
            ),
            _expected(
                "ejection_seat_armed",
                "Ejection seat",
                state.ejection_seat_armed,
                True,
            ),
            _expected("obogs_on", "OBOGS", state.obogs_on, True),
            _expected(
                "canopy_closed", "Canopy", state.canopy_state, CanopyState.CLOSED
            ),
            _expected(
                "takeoff_trim",
                "Takeoff trim",
                state.takeoff_trim_confirmed,
                True,
            ),
            _expected("wings_spread", "Wings", state.wing_fold_spread, True),
            _expected(
                "master_caution_clear", "Master caution", state.master_caution, False
            ),
            _manual(
                "flight_controls_check",
                "Flight controls — full-and-free stick and rudder check",
                checklist.manual_item_confirmed("flight_controls_check"),
                instruction=(
                    "complete a full-and-free stick and rudder sweep while checking "
                    "the FCS indications, then confirm it"
                ),
            ),
        ]
        if selected_operation is TakeoffOperation.CARRIER:
            items.append(
                _expected(
                    "launch_bar_down",
                    "Launch bar",
                    state.launch_bar_deployed,
                    True,
                )
            )
        elif selected_operation is TakeoffOperation.LAND:
            items.append(
                _expected(
                    "launch_bar_up",
                    "Launch bar",
                    state.launch_bar_deployed,
                    False,
                )
            )
        else:
            items.append(
                ReadinessItem(
                    "takeoff_operation",
                    "Takeoff operation",
                    ChecklistItemStatus.UNCONFIRMED,
                    "LAND or CARRIER",
                    None,
                    "land or carrier takeoff has not been established",
                )
            )
        return _report(tuple(items))

    @staticmethod
    def _before_taxi(
        state: AircraftState,
        history: StateHistory,
        checklist: ChecklistEngine,
        *,
        now: float,
    ) -> ReadinessReport:
        try:
            result = checklist.evaluate(
                state,
                history,
                now=now,
                checklist_id="fa18c_startup",
                stage_id="before-taxi",
            )
        except ValueError:
            return ReadinessReport(ReadinessStatus.UNKNOWN, ())
        return _report(tuple(_from_checklist(item) for item in result.items))

    @staticmethod
    def resolve_operation(
        state: AircraftState, requested: TakeoffOperation
    ) -> TakeoffOperation:
        if requested is not TakeoffOperation.AUTO:
            return requested
        if state.carrier_launch_sequence.usable and state.carrier_launch_sequence.value:
            return TakeoffOperation.CARRIER
        return TakeoffOperation.UNKNOWN

    @staticmethod
    def _phase(
        state: AircraftState,
        before_taxi: ReadinessReport,
    ) -> tuple[GroundOpsPhase, LineupState]:
        assert state.weight_on_wheels.usable
        if not bool(state.weight_on_wheels.value):
            return GroundOpsPhase.IN_FLIGHT, LineupState.TAKEOFF_ROLL
        if state.takeoff_sequence.usable and state.takeoff_sequence.value:
            airspeed = _number(state.indicated_airspeed)
            if airspeed is not None and airspeed >= 80.0:
                return GroundOpsPhase.TAKEOFF_ROLL, LineupState.TAKEOFF_ROLL
        if state.carrier_launch_sequence.usable and state.carrier_launch_sequence.value:
            return GroundOpsPhase.CARRIER_LAUNCH, LineupState.CARRIER_CONFIRMED
        if state.flight_phase is FlightPhase.POST_LANDING:
            return GroundOpsPhase.POST_LANDING, LineupState.UNCONFIRMED

        engines = _engine_state(state)
        if engines == "off":
            return GroundOpsPhase.COLD_START, LineupState.UNCONFIRMED
        if engines == "starting":
            return GroundOpsPhase.ENGINE_START, LineupState.UNCONFIRMED
        ground_speed = _number(state.ground_speed)
        if state.flight_phase is FlightPhase.TAXI or (
            engines == "running" and ground_speed is not None and ground_speed >= 3.0
        ):
            return GroundOpsPhase.TAXI, LineupState.UNCONFIRMED
        if engines == "running":
            phase = (
                GroundOpsPhase.READY_FOR_TAXI
                if before_taxi.status is ReadinessStatus.READY
                else GroundOpsPhase.PRE_TAXI
            )
            return phase, LineupState.UNCONFIRMED
        return GroundOpsPhase.UNKNOWN, LineupState.UNCONFIRMED


def _engine_state(state: AircraftState) -> str | None:
    left = _number(state.engine_rpm_left)
    right = _number(state.engine_rpm_right)
    if left is None or right is None:
        return None
    if max(left, right) <= 5.0:
        return "off"
    if min(left, right) >= 60.0:
        return "running"
    return "starting"


def _number(value: TelemetryValue[Any]) -> float | None:
    if not value.usable or not isinstance(value.value, (int, float)):
        return None
    return float(value.value)


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


def _maximum(
    item_id: str,
    label: str,
    telemetry: TelemetryValue[Any],
    maximum: float,
) -> ReadinessItem:
    value = _number(telemetry)
    if value is None:
        return ReadinessItem(
            item_id,
            label,
            ChecklistItemStatus.UNCONFIRMED,
            f"<= {maximum:g}",
            telemetry.value if telemetry.available else None,
            "telemetry is stale" if telemetry.stale else "telemetry is unavailable",
        )
    passed = value <= maximum
    return ReadinessItem(
        item_id,
        label,
        ChecklistItemStatus.COMPLETE if passed else ChecklistItemStatus.INCOMPLETE,
        f"<= {maximum:g}",
        value,
        "verified" if passed else f"observed {value:g}, limit {maximum:g}",
    )


def _manual(
    item_id: str,
    label: str,
    confirmed: bool,
    *,
    instruction: str,
) -> ReadinessItem:
    return ReadinessItem(
        item_id,
        label,
        ChecklistItemStatus.COMPLETE if confirmed else ChecklistItemStatus.UNCONFIRMED,
        instruction,
        "confirmed" if confirmed else None,
        "pilot confirmed" if confirmed else instruction,
    )


def _from_checklist(item: ChecklistItemResult) -> ReadinessItem:
    return ReadinessItem(
        item.id,
        item.label,
        item.status,
        item.expected,
        item.actual,
        item.reason,
    )


def _report(items: tuple[ReadinessItem, ...]) -> ReadinessReport:
    if any(item.status is ChecklistItemStatus.INCOMPLETE for item in items):
        status = ReadinessStatus.BLOCKED
    elif any(item.status is ChecklistItemStatus.UNCONFIRMED for item in items):
        status = ReadinessStatus.UNKNOWN
    else:
        status = ReadinessStatus.READY
    return ReadinessReport(status, items)


__all__ = [
    "GroundOpsCoordinator",
    "GroundOpsPhase",
    "GroundOpsSnapshot",
    "LineupState",
    "ReadinessItem",
    "ReadinessReport",
    "ReadinessStatus",
    "TakeoffOperation",
]
