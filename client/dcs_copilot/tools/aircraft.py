"""Fail-closed execution of allowlisted tools against authoritative local state."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from dcs_copilot.checklists import ChecklistItemResult, ChecklistResult
from dcs_copilot_protocol import (
    ALLOWED_AIRCRAFT_STATE_FIELDS,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    ControlMessage,
    ToolAuthorizationError,
    ToolProtocolError,
)

from dcs_copilot.events import ManagedAircraftEvent
from dcs_copilot.state.models import AircraftState, FlightPhase, TelemetryValue
from dcs_copilot.state.store import AircraftStateStore


class AircraftToolExecutor:
    """The only cloud-callable boundary into local aircraft knowledge."""

    def __init__(
        self,
        store: AircraftStateStore | None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._clock = clock

    def handle_control(self, message: ControlMessage) -> ControlMessage:
        try:
            request = AircraftToolRequest.from_control(message)
            result = AircraftToolResult.success(request, self.execute(request))
        except ToolProtocolError as exc:
            raw_tool = message.payload.get("tool")
            tool = raw_tool if isinstance(raw_tool, str) and raw_tool else "unknown"
            code = (
                "tool_not_allowed"
                if isinstance(exc, ToolAuthorizationError)
                else "invalid_tool_request"
            )
            result = AircraftToolResult.failure(
                tool=tool[:128],
                request_id=message.message_id,
                code=code,
                detail=str(exc),
            )
        return result.to_control()

    def execute(self, request: AircraftToolRequest) -> dict[str, Any]:
        if request.tool is AircraftToolName.GET_AIRCRAFT_STATE:
            return self._get_aircraft_state(request.arguments["fields"])
        if request.tool is AircraftToolName.GET_ACTIVE_ISSUES:
            return self._get_active_issues()
        if request.tool is AircraftToolName.GET_RECENT_EVENTS:
            return self._get_recent_events(
                seconds=request.arguments["seconds"],
                limit=request.arguments["limit"],
            )
        if request.tool is AircraftToolName.GET_FLIGHT_PHASE:
            return self._get_flight_phase()
        if request.tool is AircraftToolName.GET_CHECKLIST_STATUS:
            return self._get_checklist_status(
                checklist_id=request.arguments["checklist_id"],
                stage=request.arguments["stage"],
                include_complete=request.arguments["include_complete"],
            )
        if request.tool is AircraftToolName.GET_MISSING_CHECKLIST_ITEMS:
            return self._get_missing_checklist_items(
                checklist_id=request.arguments["checklist_id"],
                stage=request.arguments["stage"],
            )
        if request.tool is AircraftToolName.START_GUIDED_CHECKLIST:
            return self._start_guided_checklist(
                request.arguments["checklist_id"],
                request.arguments["stage"],
            )
        if request.tool is AircraftToolName.GET_NEXT_CHECKLIST_ITEM:
            return self._get_next_checklist_item()
        if request.tool is AircraftToolName.CONFIRM_MANUAL_CHECKLIST_ITEM:
            return self._confirm_manual_checklist_item(request.arguments["item_id"])
        if request.tool is AircraftToolName.STOP_GUIDED_CHECKLIST:
            return self._stop_guided_checklist()
        raise ToolAuthorizationError(f"aircraft tool is not allowed: {request.tool}")

    @property
    def _state(self) -> AircraftState:
        if self._store is None:
            return AircraftState()
        return self._store.current

    def _get_aircraft_state(self, fields: list[str]) -> dict[str, Any]:
        state = self._state
        telemetry = state.telemetry()
        values: dict[str, dict[str, Any]] = {}
        for field in fields:
            if field not in ALLOWED_AIRCRAFT_STATE_FIELDS:
                raise ToolAuthorizationError(f"aircraft state field is not allowed: {field}")
            if field == "aircraft":
                values[field] = _plain_value(state.aircraft, available=state.aircraft is not None)
            elif field == "connected":
                values[field] = _plain_value(state.connected, available=True)
            else:
                value = telemetry.get(field)
                if value is None:
                    raise ToolAuthorizationError(
                        f"aircraft state field is not exposed: {field}"
                    )
                values[field] = _telemetry_value(value)
        return {"fields": values}

    def _get_active_issues(self) -> dict[str, Any]:
        state = self._state
        issues = () if self._store is None else self._store.rule_engine.active_issues
        unavailable_rule_ids: list[str] = []
        if self._store is not None and state.connected:
            telemetry = state.telemetry()
            for rule in self._store.rule_engine.rules:
                if (
                    rule.aircraft_names is not None
                    and state.aircraft not in rule.aircraft_names
                ):
                    continue
                if (
                    rule.flight_phases is not None
                    and state.flight_phase is FlightPhase.UNKNOWN
                ):
                    unavailable_rule_ids.append(rule.id)
                    continue
                if any(
                    field not in telemetry or not telemetry[field].usable
                    for field in rule.required_fields
                ):
                    unavailable_rule_ids.append(rule.id)
        coverage = (
            "UNAVAILABLE"
            if not state.connected
            else "PARTIAL"
            if unavailable_rule_ids
            else "AVAILABLE"
        )
        return {
            "available": state.connected,
            "coverage": coverage,
            "unavailable_rule_ids": unavailable_rule_ids,
            "issues": [
                {
                    "rule_id": issue.rule_id,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "explanation": issue.explanation,
                    "data": _json_value(issue.data),
                }
                for issue in issues
            ],
        }

    def _get_recent_events(self, *, seconds: float, limit: int) -> dict[str, Any]:
        state = self._state
        managed_events: tuple[ManagedAircraftEvent, ...]
        if self._store is None:
            managed_events = ()
        else:
            now = self._clock()
            managed_events = tuple(
                managed
                for managed in self._store.event_manager.history
                if managed.observed_at >= now - seconds
            )[-limit:]
        return {
            "available": state.connected,
            "events": [
                {
                    "event_id": managed.event.event_id,
                    "rule_id": managed.event.rule_id,
                    "status": managed.event.status,
                    "severity": managed.event.severity,
                    "aircraft": managed.event.aircraft,
                    "flight_phase": managed.event.flight_phase,
                    "message": managed.event.message,
                    "data": managed.event.data,
                    "seconds_ago": max(
                        0.0,
                        round(self._clock() - managed.observed_at, 3),
                    ),
                }
                for managed in managed_events
            ],
        }

    def _get_flight_phase(self) -> dict[str, Any]:
        state = self._state
        available = state.connected and state.flight_phase is not FlightPhase.UNKNOWN
        return {
            "available": available,
            "flight_phase": state.flight_phase.value if available else None,
        }

    def _get_checklist_status(
        self,
        *,
        checklist_id: str | None,
        stage: str | None,
        include_complete: bool,
    ) -> dict[str, Any]:
        if self._store is None or not self._state.connected:
            return _empty_checklist_result()
        result = self._store.checklist_engine.evaluate(
            self._state,
            self._store.history,
            now=self._clock(),
            checklist_id=checklist_id,
            stage_id=stage,
        )
        return _checklist_result(result, include_complete=include_complete)

    def _get_missing_checklist_items(
        self,
        *,
        checklist_id: str | None,
        stage: str | None,
    ) -> dict[str, Any]:
        if self._store is None or not self._state.connected:
            return _empty_checklist_result()
        result = self._store.checklist_engine.evaluate(
            self._state,
            self._store.history,
            now=self._clock(),
            checklist_id=checklist_id,
            stage_id=stage,
        )
        return _checklist_result(
            result,
            include_complete=False,
            include_not_applicable=False,
        )

    def _start_guided_checklist(
        self, checklist_id: str, stage: str | None
    ) -> dict[str, Any]:
        if self._store is None:
            raise ToolAuthorizationError("checklist engine is unavailable")
        self._store.checklist_engine.start(checklist_id, stage)
        active_stage = stage or self._store.checklist_engine.definitions[
            checklist_id
        ].stages[0].id
        return {"started": True, "checklist_id": checklist_id, "stage": active_stage}

    def _get_next_checklist_item(self) -> dict[str, Any]:
        if self._store is None or not self._state.connected:
            return {"item": None}
        item = self._store.checklist_engine.next_item(
            self._state,
            self._store.history,
            now=self._clock(),
        )
        return {"item": _checklist_item(item) if item is not None else None}

    def _confirm_manual_checklist_item(self, item_id: str) -> dict[str, Any]:
        if self._store is None:
            raise ToolAuthorizationError("checklist engine is unavailable")
        self._store.checklist_engine.confirm_manual_item(item_id)
        return {"confirmed": True, "item_id": item_id}

    def _stop_guided_checklist(self) -> dict[str, Any]:
        if self._store is not None:
            self._store.checklist_engine.stop()
        return {"stopped": True}


def _telemetry_value(telemetry: TelemetryValue[Any]) -> dict[str, Any]:
    available = telemetry.available
    return {
        "status": telemetry.status.value,
        "value": _json_value(telemetry.value) if available else None,
        "updated_at": telemetry.updated_at,
        "source": telemetry.source,
    }


def _plain_value(value: Any, *, available: bool) -> dict[str, Any]:
    return {
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "value": _json_value(value) if available else None,
        "updated_at": None,
        "source": "local_state",
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _empty_checklist_result() -> dict[str, Any]:
    return {
        "available": False,
        "checklist_id": "unavailable",
        "aircraft": "unavailable",
        "stage": "unavailable",
        "complete": False,
        "items": [],
    }


def _checklist_result(
    result: ChecklistResult,
    *,
    include_complete: bool,
    include_not_applicable: bool = True,
) -> dict[str, Any]:
    items: list[ChecklistItemResult] = [
        *result.incomplete_items,
        *result.unconfirmed_items,
    ]
    if include_not_applicable:
        items = [*items, *result.not_applicable_items]
    if include_complete:
        items = [*result.complete_items, *items]
    return {
        "available": True,
        "checklist_id": result.checklist_id,
        "aircraft": result.aircraft,
        "stage": result.stage,
        "complete": result.complete,
        "items": [_checklist_item(item) for item in items],
    }


def _checklist_item(item: ChecklistItemResult) -> dict[str, Any]:
    return {
        "id": item.id,
        "label": item.label,
        "status": item.status.value,
        "expected": _json_value(item.expected),
        "actual": _json_value(item.actual),
        "reason": item.reason,
        "verification_type": item.verification_type.value,
        "observed_at": item.observed_at,
    }
