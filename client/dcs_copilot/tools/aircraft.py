"""Fail-closed execution of allowlisted tools against authoritative local state."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from dcs_copilot_protocol import (
    ALLOWED_AIRCRAFT_STATE_FIELDS,
    AircraftToolName,
    AircraftToolRequest,
    AircraftToolResult,
    ControlMessage,
    ToolAuthorizationError,
    ToolProtocolError,
)

from dcs_copilot.state.history import StateTransition
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
        transitions: tuple[StateTransition, ...]
        if self._store is None:
            transitions = ()
        else:
            now = self._clock()
            transitions = tuple(
                transition
                for transition in self._store.history.transitions(since=now - seconds)
                if transition.field in ALLOWED_AIRCRAFT_STATE_FIELDS
            )[-limit:]
        return {
            "available": state.connected,
            "events": [
                {
                    "field": transition.field,
                    "old_value": _json_value(transition.old_value),
                    "new_value": _json_value(transition.new_value),
                    "seconds_ago": max(0.0, round(self._clock() - transition.timestamp, 3)),
                }
                for transition in transitions
            ],
        }

    def _get_flight_phase(self) -> dict[str, Any]:
        state = self._state
        available = state.connected and state.flight_phase is not FlightPhase.UNKNOWN
        return {
            "available": available,
            "flight_phase": state.flight_phase.value if available else None,
        }


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
