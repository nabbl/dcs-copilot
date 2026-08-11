"""Versioned schemas for narrow read-only aircraft tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .events import EVENT_SEVERITIES, EVENT_STATUSES
from .messages import ControlMessage, ProtocolError

AIRCRAFT_TOOL_VERSION = 1
MAX_STATE_FIELDS = 16
MAX_RECENT_EVENTS = 20
MAX_RECENT_EVENT_SECONDS = 300.0
MAX_CHECKLIST_ITEMS = 64


class AircraftToolName(StrEnum):
    GET_AIRCRAFT_STATE = "get_aircraft_state"
    GET_ACTIVE_ISSUES = "get_active_issues"
    GET_RECENT_EVENTS = "get_recent_events"
    GET_FLIGHT_PHASE = "get_flight_phase"
    GET_CHECKLIST_STATUS = "get_checklist_status"
    GET_MISSING_CHECKLIST_ITEMS = "get_missing_checklist_items"
    START_GUIDED_CHECKLIST = "start_guided_checklist"
    GET_NEXT_CHECKLIST_ITEM = "get_next_checklist_item"
    CONFIRM_MANUAL_CHECKLIST_ITEM = "confirm_manual_checklist_item"
    STOP_GUIDED_CHECKLIST = "stop_guided_checklist"


ALLOWED_AIRCRAFT_STATE_FIELDS = frozenset(
    {
        "aircraft",
        "connected",
        "indicated_airspeed",
        "altitude_msl",
        "heading",
        "gear_position",
        "flap_position",
        "canopy_state",
        "master_arm",
        "selected_weapon",
        "fuel_quantity",
        "master_caution",
        "parking_brake",
        "speed_brake",
        "refueling_probe",
        "hook_position",
        "hook_commanded_down",
        "ejection_seat_armed",
        "obogs_on",
        "weight_on_wheels",
        "engine_rpm_left",
        "engine_rpm_right",
        "throttle_left",
        "throttle_right",
        "gear_commanded_down",
        "launch_bar_deployed",
        "wing_fold_spread",
        "takeoff_trim_pressed",
        "takeoff_trim_confirmed",
        "master_mode_combat",
        "airborne",
        "takeoff_sequence",
        "carrier_launch_sequence",
        "carrier_recovery",
    }
)


class ToolProtocolError(ProtocolError):
    pass


class ToolAuthorizationError(ToolProtocolError):
    pass


@dataclass(frozen=True, slots=True)
class AircraftToolRequest:
    tool: AircraftToolName
    arguments: dict[str, Any]
    request_id: str

    @classmethod
    def create(
        cls,
        tool: AircraftToolName | str,
        arguments: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> AircraftToolRequest:
        parsed_tool = _parse_tool_name(tool)
        return cls(
            parsed_tool,
            validate_tool_arguments(parsed_tool, arguments),
            request_id or str(uuid4()),
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> AircraftToolRequest:
        if message.type != "tool.request":
            raise ToolProtocolError("expected tool.request")
        _require_exact_keys(
            message.payload,
            {"tool_version", "tool", "arguments"},
            "tool.request payload",
        )
        _require_tool_version(message.payload.get("tool_version"))
        tool = _parse_tool_name(message.payload.get("tool"))
        arguments = message.payload.get("arguments")
        if not isinstance(arguments, dict):
            raise ToolProtocolError("tool arguments must be an object")
        return cls(tool, validate_tool_arguments(tool, arguments), message.message_id)

    def to_control(self) -> ControlMessage:
        return ControlMessage(
            "tool.request",
            {
                "tool_version": AIRCRAFT_TOOL_VERSION,
                "tool": self.tool.value,
                "arguments": self.arguments,
            },
            message_id=self.request_id,
        )


@dataclass(frozen=True, slots=True)
class AircraftToolResult:
    tool: str
    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None

    @classmethod
    def success(
        cls,
        request: AircraftToolRequest,
        result: dict[str, Any],
    ) -> AircraftToolResult:
        return cls(
            request.tool.value,
            request.request_id,
            True,
            result=validate_tool_result(request.tool, result),
        )

    @classmethod
    def failure(
        cls,
        *,
        tool: str,
        request_id: str,
        code: str,
        detail: str,
    ) -> AircraftToolResult:
        return cls(
            tool,
            request_id,
            False,
            error={"code": code, "detail": detail},
        )

    @classmethod
    def from_control(cls, message: ControlMessage) -> AircraftToolResult:
        if message.type != "tool.result":
            raise ToolProtocolError("expected tool.result")
        if not message.correlation_id:
            raise ToolProtocolError("tool.result requires correlation_id")
        _require_exact_keys(
            message.payload,
            {"tool_version", "tool", "ok", "result", "error"},
            "tool.result payload",
            optional={"result", "error"},
        )
        _require_tool_version(message.payload.get("tool_version"))
        tool = message.payload.get("tool")
        ok = message.payload.get("ok")
        if not isinstance(tool, str) or not tool:
            raise ToolProtocolError("tool.result tool must be a non-empty string")
        if not isinstance(ok, bool):
            raise ToolProtocolError("tool.result ok must be a boolean")
        result = message.payload.get("result")
        error = message.payload.get("error")
        if ok:
            if not isinstance(result, dict) or error is not None:
                raise ToolProtocolError("successful tool.result requires only a result object")
            parsed_tool = _parse_tool_name(tool)
            return cls(
                tool,
                message.correlation_id,
                True,
                result=validate_tool_result(parsed_tool, result),
            )
        if result is not None or not isinstance(error, dict):
            raise ToolProtocolError("failed tool.result requires only an error object")
        code = error.get("code")
        detail = error.get("detail")
        if not isinstance(code, str) or not code:
            raise ToolProtocolError("tool error code must be a non-empty string")
        if not isinstance(detail, str) or not detail:
            raise ToolProtocolError("tool error detail must be a non-empty string")
        return cls(
            tool,
            message.correlation_id,
            False,
            error={"code": code, "detail": detail},
        )

    def to_control(self) -> ControlMessage:
        payload: dict[str, Any] = {
            "tool_version": AIRCRAFT_TOOL_VERSION,
            "tool": self.tool,
            "ok": self.ok,
        }
        if self.ok:
            if self.result is None:
                raise ToolProtocolError("successful tool result is missing result")
            payload["result"] = self.result
        else:
            if self.error is None:
                raise ToolProtocolError("failed tool result is missing error")
            payload["error"] = self.error
        return ControlMessage(
            "tool.result",
            payload,
            correlation_id=self.request_id,
        )


def validate_tool_arguments(
    tool: AircraftToolName,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if tool is AircraftToolName.GET_AIRCRAFT_STATE:
        _require_exact_keys(arguments, {"fields"}, "get_aircraft_state arguments")
        fields = arguments.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ToolProtocolError("get_aircraft_state fields must be a non-empty list")
        if len(fields) > MAX_STATE_FIELDS:
            raise ToolProtocolError(
                f"get_aircraft_state accepts at most {MAX_STATE_FIELDS} fields"
            )
        if any(not isinstance(field, str) for field in fields):
            raise ToolProtocolError("get_aircraft_state fields must contain strings")
        if len(fields) != len(set(fields)):
            raise ToolProtocolError("get_aircraft_state fields must be unique")
        forbidden = sorted(set(fields) - ALLOWED_AIRCRAFT_STATE_FIELDS)
        if forbidden:
            raise ToolAuthorizationError(
                "aircraft state fields are not allowed: " + ", ".join(forbidden)
            )
        return {"fields": fields.copy()}

    if tool in {
        AircraftToolName.GET_ACTIVE_ISSUES,
        AircraftToolName.GET_FLIGHT_PHASE,
    }:
        _require_exact_keys(arguments, set(), f"{tool.value} arguments")
        return {}

    if tool is AircraftToolName.GET_RECENT_EVENTS:
        _require_exact_keys(
            arguments,
            {"seconds", "limit"},
            "get_recent_events arguments",
            optional={"seconds", "limit"},
        )
        seconds = arguments.get("seconds", 30.0)
        limit = arguments.get("limit", 10)
        if (
            not isinstance(seconds, (int, float))
            or isinstance(seconds, bool)
            or not 0 < float(seconds) <= MAX_RECENT_EVENT_SECONDS
        ):
            raise ToolProtocolError(
                f"recent event seconds must be between 0 and {MAX_RECENT_EVENT_SECONDS:g}"
            )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= MAX_RECENT_EVENTS
        ):
            raise ToolProtocolError(
                f"recent event limit must be between 1 and {MAX_RECENT_EVENTS}"
            )
        return {"seconds": float(seconds), "limit": limit}

    if tool in {
        AircraftToolName.GET_CHECKLIST_STATUS,
        AircraftToolName.GET_MISSING_CHECKLIST_ITEMS,
    }:
        _require_exact_keys(
            arguments,
            {"checklist_id", "stage", "include_complete"},
            f"{tool.value} arguments",
            optional={"checklist_id", "stage", "include_complete"},
        )
        checklist_id = _optional_string(arguments.get("checklist_id"), "checklist_id")
        stage = _optional_string(arguments.get("stage"), "stage")
        include_complete = arguments.get("include_complete", False)
        if not isinstance(include_complete, bool):
            raise ToolProtocolError("include_complete must be a boolean")
        return {
            "checklist_id": checklist_id,
            "stage": stage,
            "include_complete": include_complete,
        }

    if tool is AircraftToolName.START_GUIDED_CHECKLIST:
        _require_exact_keys(
            arguments,
            {"checklist_id", "stage"},
            "start_guided_checklist arguments",
            optional={"stage"},
        )
        checklist_id = arguments.get("checklist_id")
        if not isinstance(checklist_id, str) or not checklist_id.strip():
            raise ToolProtocolError("checklist_id must be a non-empty string")
        return {
            "checklist_id": checklist_id.strip(),
            "stage": _optional_string(arguments.get("stage"), "stage"),
        }

    if tool is AircraftToolName.CONFIRM_MANUAL_CHECKLIST_ITEM:
        _require_exact_keys(
            arguments,
            {"item_id"},
            "confirm_manual_checklist_item arguments",
        )
        item_id = arguments.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ToolProtocolError("item_id must be a non-empty string")
        return {"item_id": item_id.strip()}

    if tool in {
        AircraftToolName.GET_NEXT_CHECKLIST_ITEM,
        AircraftToolName.STOP_GUIDED_CHECKLIST,
    }:
        _require_exact_keys(arguments, set(), f"{tool.value} arguments")
        return {}

    raise ToolAuthorizationError(f"aircraft tool is not allowed: {tool}")


def validate_tool_result(
    tool: AircraftToolName,
    result: dict[str, Any],
) -> dict[str, Any]:
    if tool is AircraftToolName.GET_AIRCRAFT_STATE:
        _require_exact_keys(result, {"fields"}, "get_aircraft_state result")
        fields = result.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ToolProtocolError("aircraft state result fields must be a non-empty object")
        if len(fields) > MAX_STATE_FIELDS:
            raise ToolProtocolError(
                f"aircraft state result accepts at most {MAX_STATE_FIELDS} fields"
            )
        for name, item in fields.items():
            if name not in ALLOWED_AIRCRAFT_STATE_FIELDS:
                raise ToolAuthorizationError(
                    f"aircraft state result field is not allowed: {name}"
                )
            if not isinstance(item, dict):
                raise ToolProtocolError(f"aircraft state field {name} must be an object")
            _require_exact_keys(
                item,
                {"status", "value", "updated_at", "source"},
                f"aircraft state field {name}",
            )
            status = item.get("status")
            if status not in {"AVAILABLE", "STALE", "UNAVAILABLE"}:
                raise ToolProtocolError(f"aircraft state field {name} has invalid status")
            if status == "UNAVAILABLE" and item.get("value") is not None:
                raise ToolProtocolError(
                    f"unavailable aircraft state field {name} must have a null value"
                )
            updated_at = item.get("updated_at")
            if updated_at is not None and (
                not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool)
            ):
                raise ToolProtocolError(f"aircraft state field {name} has invalid updated_at")
            source = item.get("source")
            if source is not None and not isinstance(source, str):
                raise ToolProtocolError(f"aircraft state field {name} has invalid source")
        return result.copy()

    if tool is AircraftToolName.GET_ACTIVE_ISSUES:
        _require_exact_keys(
            result,
            {"available", "coverage", "unavailable_rule_ids", "issues"},
            "get_active_issues result",
        )
        _require_boolean(result.get("available"), "active issues available")
        if result.get("coverage") not in {"AVAILABLE", "PARTIAL", "UNAVAILABLE"}:
            raise ToolProtocolError("active issues coverage is invalid")
        unavailable = result.get("unavailable_rule_ids")
        if not isinstance(unavailable, list) or any(
            not isinstance(rule_id, str) or not rule_id for rule_id in unavailable
        ):
            raise ToolProtocolError("unavailable_rule_ids must be a list of strings")
        issues = result.get("issues")
        if not isinstance(issues, list):
            raise ToolProtocolError("active issues must be a list")
        for issue in issues:
            if not isinstance(issue, dict):
                raise ToolProtocolError("each active issue must be an object")
            _require_exact_keys(
                issue,
                {"rule_id", "severity", "message", "explanation", "data"},
                "active issue",
            )
            for key in ("rule_id", "message", "explanation"):
                if not isinstance(issue.get(key), str) or not issue[key]:
                    raise ToolProtocolError(f"active issue {key} must be a string")
            if issue.get("severity") not in {"INFO", "ADVISORY", "WARNING", "CRITICAL"}:
                raise ToolProtocolError("active issue severity is invalid")
            if not isinstance(issue.get("data"), dict):
                raise ToolProtocolError("active issue data must be an object")
        return result.copy()

    if tool in {
        AircraftToolName.GET_CHECKLIST_STATUS,
        AircraftToolName.GET_MISSING_CHECKLIST_ITEMS,
    }:
        _validate_checklist_result(result, require_complete=tool is AircraftToolName.GET_CHECKLIST_STATUS)
        return result.copy()

    if tool is AircraftToolName.START_GUIDED_CHECKLIST:
        _require_exact_keys(
            result, {"started", "checklist_id", "stage"}, "start_guided_checklist result"
        )
        _require_boolean(result.get("started"), "checklist started")
        _require_string(result.get("checklist_id"), "checklist_id")
        _require_string(result.get("stage"), "stage")
        return result.copy()

    if tool is AircraftToolName.GET_NEXT_CHECKLIST_ITEM:
        _require_exact_keys(result, {"item"}, "get_next_checklist_item result")
        item = result.get("item")
        if item is not None:
            _validate_checklist_item(item)
        return result.copy()

    if tool is AircraftToolName.CONFIRM_MANUAL_CHECKLIST_ITEM:
        _require_exact_keys(result, {"confirmed", "item_id"}, "confirm_manual_checklist_item result")
        _require_boolean(result.get("confirmed"), "manual item confirmed")
        _require_string(result.get("item_id"), "item_id")
        return result.copy()

    if tool is AircraftToolName.STOP_GUIDED_CHECKLIST:
        _require_exact_keys(result, {"stopped"}, "stop_guided_checklist result")
        _require_boolean(result.get("stopped"), "checklist stopped")
        return result.copy()

    if tool is AircraftToolName.GET_RECENT_EVENTS:
        _require_exact_keys(result, {"available", "events"}, "get_recent_events result")
        _require_boolean(result.get("available"), "recent events available")
        events = result.get("events")
        if not isinstance(events, list) or len(events) > MAX_RECENT_EVENTS:
            raise ToolProtocolError(
                f"recent events must be a list of at most {MAX_RECENT_EVENTS} items"
            )
        for event in events:
            if not isinstance(event, dict):
                raise ToolProtocolError("each recent event must be an object")
            _require_exact_keys(
                event,
                {
                    "event_id",
                    "rule_id",
                    "status",
                    "severity",
                    "aircraft",
                    "flight_phase",
                    "message",
                    "data",
                    "seconds_ago",
                },
                "recent event",
            )
            for key in ("event_id", "rule_id", "aircraft", "message"):
                if not isinstance(event.get(key), str) or not event[key]:
                    raise ToolProtocolError(f"recent event {key} must be a string")
            if event.get("status") not in EVENT_STATUSES:
                raise ToolProtocolError("recent event status is invalid")
            if event.get("severity") not in EVENT_SEVERITIES:
                raise ToolProtocolError("recent event severity is invalid")
            phase = event.get("flight_phase")
            if phase is not None and not isinstance(phase, str):
                raise ToolProtocolError(
                    "recent event flight_phase must be a string or null"
                )
            if not isinstance(event.get("data"), dict):
                raise ToolProtocolError("recent event data must be an object")
            seconds_ago = event.get("seconds_ago")
            if (
                not isinstance(seconds_ago, (int, float))
                or isinstance(seconds_ago, bool)
                or seconds_ago < 0
            ):
                raise ToolProtocolError("recent event seconds_ago must be non-negative")
        return result.copy()

    if tool is AircraftToolName.GET_FLIGHT_PHASE:
        _require_exact_keys(
            result,
            {"available", "flight_phase"},
            "get_flight_phase result",
        )
        available = result.get("available")
        _require_boolean(available, "flight phase available")
        phase = result.get("flight_phase")
        if available and (not isinstance(phase, str) or not phase):
            raise ToolProtocolError("available flight phase must be a string")
        if not available and phase is not None:
            raise ToolProtocolError("unavailable flight phase must be null")
        return result.copy()

    raise ToolAuthorizationError(f"aircraft tool is not allowed: {tool}")


def _parse_tool_name(value: object) -> AircraftToolName:
    if not isinstance(value, str) or not value:
        raise ToolProtocolError("tool name must be a non-empty string")
    try:
        return AircraftToolName(value)
    except ValueError as exc:
        raise ToolAuthorizationError(f"aircraft tool is not allowed: {value}") from exc


def _require_tool_version(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolProtocolError("tool_version must be an integer")
    if value != AIRCRAFT_TOOL_VERSION:
        raise ToolProtocolError(f"unsupported aircraft tool version {value}")


def _require_boolean(value: object, label: str) -> None:
    if not isinstance(value, bool):
        raise ToolProtocolError(f"{label} must be a boolean")


def _require_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ToolProtocolError(f"{label} must be a non-empty string")


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolProtocolError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_checklist_result(result: dict[str, Any], *, require_complete: bool) -> None:
    required = {
        "available",
        "checklist_id",
        "aircraft",
        "stage",
        "complete",
        "items",
    }
    _require_exact_keys(result, required, "checklist result")
    _require_boolean(result.get("available"), "checklist available")
    _require_string(result.get("checklist_id"), "checklist_id")
    _require_string(result.get("aircraft"), "aircraft")
    _require_string(result.get("stage"), "stage")
    _require_boolean(result.get("complete"), "checklist complete")
    items = result.get("items")
    if not isinstance(items, list) or len(items) > MAX_CHECKLIST_ITEMS:
        raise ToolProtocolError(
            f"checklist result items must be a list of at most {MAX_CHECKLIST_ITEMS}"
        )
    if require_complete and not items:
        raise ToolProtocolError("checklist status result must include items")
    for item in items:
        _validate_checklist_item(item)


def _validate_checklist_item(item: object) -> None:
    if not isinstance(item, dict):
        raise ToolProtocolError("checklist item must be an object")
    _require_exact_keys(
        item,
        {
            "id",
            "label",
            "status",
            "expected",
            "actual",
            "reason",
            "verification_type",
            "observed_at",
        },
        "checklist item",
    )
    _require_string(item.get("id"), "checklist item id")
    _require_string(item.get("label"), "checklist item label")
    if item.get("status") not in {
        "complete",
        "incomplete",
        "unconfirmed",
        "not_applicable",
    }:
        raise ToolProtocolError("checklist item status is invalid")
    if item.get("verification_type") not in {"state", "action", "derived", "manual"}:
        raise ToolProtocolError("checklist item verification_type is invalid")
    _require_string(item.get("reason"), "checklist item reason")
    observed_at = item.get("observed_at")
    if observed_at is not None and (
        not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool)
    ):
        raise ToolProtocolError("checklist item observed_at is invalid")


def _require_exact_keys(
    value: dict[str, Any],
    allowed: set[str],
    label: str,
    *,
    optional: set[str] | None = None,
) -> None:
    optional_keys = optional or set()
    required = allowed - optional_keys
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    if missing:
        raise ToolProtocolError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise ToolProtocolError(f"{label} contains unknown fields: {', '.join(unknown)}")
