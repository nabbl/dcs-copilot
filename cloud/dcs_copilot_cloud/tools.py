"""Deterministic backend aircraft tools reading AircraftStateStore directly."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any
from uuid import uuid4

from .checklists.models import ChecklistItemResult, ChecklistResult
from .events.models import CloudManagedEvent
from .flight_ops import FlightOpsSnapshot
from .ground_ops import (
    GroundOpsSnapshot,
    ReadinessItem,
    ReadinessReport,
    ReadinessStatus,
    TakeoffOperation,
)
from .hornet_knowledge import (
    HORNET_KNOWLEDGE_VERSION,
    HornetKnowledgeCard,
    HornetKnowledgeTopic,
    get_hornet_knowledge_card,
)
from .state.models import AircraftState, FlightPhase, TelemetryValue
from .state.store import AircraftStateStore

MAX_STATE_FIELDS = 16
MAX_RECENT_EVENTS = 20
MAX_RECENT_EVENT_SECONDS = 300.0
MAX_CHECKLIST_ITEMS = 64

EVENT_STATUSES = frozenset({"RAISED", "RESOLVED", "DISABLED"})
EVENT_SEVERITIES = frozenset({"INFO", "ADVISORY", "WARNING", "CRITICAL"})


class ToolProtocolError(ValueError):
    pass


class ToolAuthorizationError(ToolProtocolError):
    pass


def aircraft_tool_error_result(exc: Exception) -> dict[str, Any]:
    """Convert a rejected backend tool call into bounded data for the LLM."""

    code = (
        "invalid_aircraft_tool"
        if isinstance(exc, ToolProtocolError)
        else "aircraft_tool_failed"
    )
    return {
        "available": False,
        "error": {"code": code, "detail": str(exc)},
    }


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
    GET_GROUND_OPS_STATUS = "get_ground_ops_status"
    GET_TAKEOFF_READINESS = "get_takeoff_readiness"
    GET_FLIGHT_STATUS = "get_flight_status"
    GET_HORNET_KNOWLEDGE = "get_hornet_knowledge"


AIRCRAFT_TOOL_NAMES = tuple(item.value for item in AircraftToolName)


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
        "battery_on",
        "apu_ready",
        "left_generator_normal",
        "right_generator_normal",
        "bleed_air_normal",
        "ins_mode",
        "taxi_light_on",
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


def validate_tool_arguments(
    tool: AircraftToolName,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if tool is AircraftToolName.GET_AIRCRAFT_STATE:
        _require_exact_keys(arguments, {"fields"}, "get_aircraft_state arguments")
        fields = arguments.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ToolProtocolError(
                "get_aircraft_state fields must be a non-empty list"
            )
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
        AircraftToolName.GET_GROUND_OPS_STATUS,
        AircraftToolName.GET_FLIGHT_STATUS,
    }:
        _require_exact_keys(arguments, set(), f"{tool.value} arguments")
        return {}

    if tool is AircraftToolName.GET_TAKEOFF_READINESS:
        _require_exact_keys(
            arguments,
            {"operation"},
            "get_takeoff_readiness arguments",
            optional={"operation"},
        )
        operation = arguments.get("operation", TakeoffOperation.AUTO.value)
        if not isinstance(operation, str) or operation not in {
            TakeoffOperation.AUTO.value,
            TakeoffOperation.LAND.value,
            TakeoffOperation.CARRIER.value,
        }:
            raise ToolProtocolError("takeoff operation must be AUTO, LAND, or CARRIER")
        return {"operation": operation}

    if tool is AircraftToolName.GET_HORNET_KNOWLEDGE:
        _require_exact_keys(
            arguments,
            {"topic"},
            "get_hornet_knowledge arguments",
        )
        topic = arguments.get("topic")
        if not isinstance(topic, str):
            raise ToolProtocolError("Hornet knowledge topic must be a string")
        try:
            parsed_topic = HornetKnowledgeTopic(topic)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in HornetKnowledgeTopic)
            raise ToolProtocolError(
                f"Hornet knowledge topic must be one of: {allowed}"
            ) from exc
        return {"topic": parsed_topic.value}

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
            raise ToolProtocolError(
                "aircraft state result fields must be a non-empty object"
            )
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
                raise ToolProtocolError(
                    f"aircraft state field {name} must be an object"
                )
            _require_exact_keys(
                item,
                {"status", "value", "updated_at", "source"},
                f"aircraft state field {name}",
            )
            status = item.get("status")
            if status not in {"AVAILABLE", "STALE", "UNAVAILABLE"}:
                raise ToolProtocolError(
                    f"aircraft state field {name} has invalid status"
                )
            if status == "UNAVAILABLE" and item.get("value") is not None:
                raise ToolProtocolError(
                    f"unavailable aircraft state field {name} must have a null value"
                )
            updated_at = item.get("updated_at")
            if updated_at is not None and (
                not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool)
            ):
                raise ToolProtocolError(
                    f"aircraft state field {name} has invalid updated_at"
                )
            source = item.get("source")
            if source is not None and not isinstance(source, str):
                raise ToolProtocolError(
                    f"aircraft state field {name} has invalid source"
                )
        return result.copy()

    if tool is AircraftToolName.GET_ACTIVE_ISSUES:
        _require_exact_keys(
            result,
            {"available", "coverage", "unavailable_rule_ids", "issues"},
            "get_active_issues result",
            optional={"readiness", "ready_confirmed"},
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
        if "readiness" in result and result.get("readiness") is not False:
            raise ToolProtocolError("active issues readiness must be false")
        if "ready_confirmed" in result and result.get("ready_confirmed") is not False:
            raise ToolProtocolError("active issues ready_confirmed must be false")
        return result.copy()

    if tool in {
        AircraftToolName.GET_CHECKLIST_STATUS,
        AircraftToolName.GET_MISSING_CHECKLIST_ITEMS,
    }:
        _validate_checklist_result(
            result, require_complete=tool is AircraftToolName.GET_CHECKLIST_STATUS
        )
        return result.copy()

    if tool is AircraftToolName.START_GUIDED_CHECKLIST:
        _require_exact_keys(
            result,
            {"started", "checklist_id", "stage"},
            "start_guided_checklist result",
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
        _require_exact_keys(
            result, {"confirmed", "item_id"}, "confirm_manual_checklist_item result"
        )
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

    if tool is AircraftToolName.GET_GROUND_OPS_STATUS:
        _require_exact_keys(
            result,
            {
                "available",
                "phase",
                "lineup_state",
                "takeoff_operation",
                "before_taxi",
                "takeoff",
            },
            "get_ground_ops_status result",
        )
        _require_boolean(result.get("available"), "ground operations available")
        _require_string(result.get("phase"), "ground operations phase")
        _require_string(result.get("lineup_state"), "lineup state")
        _require_string(result.get("takeoff_operation"), "takeoff operation")
        _validate_readiness_report(result.get("before_taxi"), "before-taxi readiness")
        _validate_readiness_report(result.get("takeoff"), "takeoff readiness")
        return result.copy()

    if tool is AircraftToolName.GET_TAKEOFF_READINESS:
        _require_exact_keys(
            result,
            {"available", "operation", "status", "blocking_items", "unknown_items"},
            "get_takeoff_readiness result",
        )
        _require_boolean(result.get("available"), "takeoff readiness available")
        _require_string(result.get("operation"), "takeoff operation")
        _validate_readiness_report(
            {
                "status": result.get("status"),
                "blocking_items": result.get("blocking_items"),
                "unknown_items": result.get("unknown_items"),
            },
            "takeoff readiness",
        )
        return result.copy()

    if tool is AircraftToolName.GET_FLIGHT_STATUS:
        _require_exact_keys(
            result,
            {
                "available",
                "aircraft",
                "flight_phase",
                "flight_stage",
                "key_state",
                "issues_coverage",
                "active_issue_count",
                "highest_issue_severity",
                "departure_cleanup",
            },
            "get_flight_status result",
        )
        _require_boolean(result.get("available"), "flight status available")
        for key in ("aircraft", "flight_phase", "flight_stage"):
            value = result.get(key)
            if value is not None and (not isinstance(value, str) or not value):
                raise ToolProtocolError(f"flight status {key} must be a string or null")
        key_state = result.get("key_state")
        if not isinstance(key_state, dict):
            raise ToolProtocolError("flight status key_state must be an object")
        _require_exact_keys(
            key_state,
            {"indicated_airspeed", "altitude_msl", "heading", "fuel_quantity"},
            "flight status key_state",
        )
        for name, item in key_state.items():
            _validate_telemetry_result(item, f"flight status {name}")
        if result.get("issues_coverage") not in {
            "AVAILABLE",
            "PARTIAL",
            "UNAVAILABLE",
        }:
            raise ToolProtocolError("flight status issues coverage is invalid")
        issue_count = result.get("active_issue_count")
        if (
            not isinstance(issue_count, int)
            or isinstance(issue_count, bool)
            or issue_count < 0
        ):
            raise ToolProtocolError(
                "flight status active_issue_count must be non-negative"
            )
        severity = result.get("highest_issue_severity")
        if severity is not None and severity not in EVENT_SEVERITIES:
            raise ToolProtocolError("flight status highest issue severity is invalid")
        _validate_readiness_report(result.get("departure_cleanup"), "departure cleanup")
        return result.copy()

    if tool is AircraftToolName.GET_HORNET_KNOWLEDGE:
        _validate_hornet_knowledge_result(result)
        return result.copy()

    raise ToolAuthorizationError(f"aircraft tool is not allowed: {tool}")


def _parse_tool_name(value: object) -> AircraftToolName:
    if not isinstance(value, str) or not value:
        raise ToolProtocolError("tool name must be a non-empty string")
    try:
        return AircraftToolName(value)
    except ValueError as exc:
        raise ToolAuthorizationError(f"aircraft tool is not allowed: {value}") from exc


def _require_boolean(value: object, label: str) -> None:
    if not isinstance(value, bool):
        raise ToolProtocolError(f"{label} must be a boolean")


def _validate_telemetry_result(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise ToolProtocolError(f"{label} must be an object")
    _require_exact_keys(value, {"status", "value", "updated_at", "source"}, label)
    if value.get("status") not in {"AVAILABLE", "STALE", "UNAVAILABLE"}:
        raise ToolProtocolError(f"{label} status is invalid")
    if value.get("status") == "UNAVAILABLE" and value.get("value") is not None:
        raise ToolProtocolError(f"{label} unavailable value must be null")


def _validate_hornet_knowledge_result(result: dict[str, Any]) -> None:
    _require_exact_keys(
        result,
        {"available", "corpus_version", "card"},
        "get_hornet_knowledge result",
    )
    _require_boolean(result.get("available"), "Hornet knowledge available")
    _require_string(result.get("corpus_version"), "Hornet knowledge corpus_version")
    card = result.get("card")
    if not isinstance(card, dict):
        raise ToolProtocolError("Hornet knowledge card must be an object")
    _require_exact_keys(
        card,
        {
            "id",
            "topic",
            "title",
            "aircraft",
            "applicability",
            "summary",
            "steps",
            "cautions",
            "source",
        },
        "Hornet knowledge card",
    )
    for key in ("id", "topic", "title", "aircraft", "applicability", "summary"):
        _require_string(card.get(key), f"Hornet knowledge card {key}")
    if card.get("topic") not in {item.value for item in HornetKnowledgeTopic}:
        raise ToolProtocolError("Hornet knowledge card topic is invalid")
    for key in ("steps", "cautions"):
        values = card.get(key)
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item for item in values
        ):
            raise ToolProtocolError(f"Hornet knowledge card {key} must be strings")
    source = card.get("source")
    if not isinstance(source, dict):
        raise ToolProtocolError("Hornet knowledge source must be an object")
    source_keys = {
        "publisher",
        "title",
        "section",
        "pages",
        "url",
        "document_sha256",
        "document_created_at",
        "reviewed_on",
    }
    _require_exact_keys(source, source_keys, "Hornet knowledge source")
    for key in source_keys:
        _require_string(source.get(key), f"Hornet knowledge source {key}")


def _require_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ToolProtocolError(f"{label} must be a non-empty string")


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolProtocolError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_checklist_result(
    result: dict[str, Any], *, require_complete: bool
) -> None:
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


def _validate_readiness_report(value: object, label: str) -> None:
    if not isinstance(value, dict):
        raise ToolProtocolError(f"{label} must be an object")
    _require_exact_keys(
        value,
        {"status", "blocking_items", "unknown_items"},
        label,
    )
    if value.get("status") not in {"READY", "BLOCKED", "UNKNOWN", "NOT_APPLICABLE"}:
        raise ToolProtocolError(f"{label} status is invalid")
    for key in ("blocking_items", "unknown_items"):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > MAX_CHECKLIST_ITEMS:
            raise ToolProtocolError(f"{label} {key} must be a bounded list")
        for item in items:
            if not isinstance(item, dict):
                raise ToolProtocolError(f"{label} {key} item must be an object")
            _require_exact_keys(
                item,
                {"id", "label", "status", "expected", "actual", "reason"},
                f"{label} item",
            )
            _require_string(item.get("id"), f"{label} item id")
            _require_string(item.get("label"), f"{label} item label")
            if item.get("status") not in {"incomplete", "unconfirmed"}:
                raise ToolProtocolError(f"{label} item status is invalid")
            _require_string(item.get("reason"), f"{label} item reason")


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
    unknown = sorted(value.keys() - allowed - optional_keys)
    if missing:
        raise ToolProtocolError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise ToolProtocolError(
            f"{label} contains unknown fields: {', '.join(unknown)}"
        )


class BackendAircraftToolExecutor:
    """Execute aircraft tools directly against backend AircraftStateStore.

    Unlike the legacy client-broker approach, this executor never round-trips
    to the flight-sim client: the backend already owns authoritative aircraft
    semantics (telemetry normalization, rules, checklists, events, habits), so
    tool calls are answered synchronously and deterministically in-process.
    """

    def __init__(
        self,
        store: AircraftStateStore | None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._clock = clock

    def execute(self, request: AircraftToolRequest) -> dict[str, Any]:
        """Execute and return result dict. All execution is synchronous."""
        tool = request.tool
        if tool is AircraftToolName.GET_AIRCRAFT_STATE:
            return self._get_aircraft_state(request.arguments["fields"])
        if tool is AircraftToolName.GET_ACTIVE_ISSUES:
            return self._get_active_issues()
        if tool is AircraftToolName.GET_RECENT_EVENTS:
            return self._get_recent_events(
                seconds=request.arguments["seconds"],
                limit=request.arguments["limit"],
            )
        if tool is AircraftToolName.GET_FLIGHT_PHASE:
            return self._get_flight_phase()
        if tool is AircraftToolName.GET_GROUND_OPS_STATUS:
            return self._get_ground_ops_status()
        if tool is AircraftToolName.GET_TAKEOFF_READINESS:
            return self._get_takeoff_readiness(request.arguments["operation"])
        if tool is AircraftToolName.GET_FLIGHT_STATUS:
            return self._get_flight_status()
        if tool is AircraftToolName.GET_HORNET_KNOWLEDGE:
            return _hornet_knowledge_result(
                get_hornet_knowledge_card(
                    HornetKnowledgeTopic(request.arguments["topic"])
                )
            )
        if tool is AircraftToolName.GET_CHECKLIST_STATUS:
            return self._get_checklist_status(
                checklist_id=request.arguments["checklist_id"],
                stage=request.arguments["stage"],
                include_complete=request.arguments["include_complete"],
            )
        if tool is AircraftToolName.GET_MISSING_CHECKLIST_ITEMS:
            return self._get_missing_checklist_items(
                checklist_id=request.arguments["checklist_id"],
                stage=request.arguments["stage"],
            )
        if tool is AircraftToolName.START_GUIDED_CHECKLIST:
            return self._start_guided_checklist(
                request.arguments["checklist_id"],
                request.arguments["stage"],
            )
        if tool is AircraftToolName.GET_NEXT_CHECKLIST_ITEM:
            return self._advance_guided_checklist()
        if tool is AircraftToolName.CONFIRM_MANUAL_CHECKLIST_ITEM:
            return self._confirm_manual_checklist_item(request.arguments["item_id"])
        if tool is AircraftToolName.STOP_GUIDED_CHECKLIST:
            return self._stop_guided_checklist()
        raise ToolAuthorizationError(f"aircraft tool is not allowed: {tool}")

    @property
    def _state(self) -> AircraftState:
        if self._store is None:
            return AircraftState()
        return self._store.snapshot(now=self._clock())

    def _get_aircraft_state(self, fields: list[str]) -> dict[str, Any]:
        state = self._state
        telemetry = state.telemetry()
        values: dict[str, dict[str, Any]] = {}
        for field in fields:
            if field not in ALLOWED_AIRCRAFT_STATE_FIELDS:
                raise ToolAuthorizationError(
                    f"aircraft state field is not allowed: {field}"
                )
            if field == "aircraft":
                values[field] = _plain_value(
                    state.aircraft, available=state.aircraft is not None
                )
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
        # readiness/ready_confirmed are always explicitly False here: this
        # tool only reports *known* issues. An empty issues list must never
        # be interpreted by a caller as "the aircraft is ready" — coverage
        # may be partial, or readiness might require positive confirmation
        # elsewhere (e.g. a completed checklist).
        return {
            "available": state.connected,
            "coverage": coverage,
            "unavailable_rule_ids": unavailable_rule_ids,
            "readiness": False,
            "ready_confirmed": False,
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
        managed_events: tuple[CloudManagedEvent, ...]
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

    def _get_ground_ops_status(self) -> dict[str, Any]:
        if self._store is None:
            return _ground_ops_result(None)
        snapshot = self._store.ground_ops.evaluate(
            self._state,
            self._store.history,
            self._store.checklist_engine,
            now=self._clock(),
        )
        return _ground_ops_result(snapshot)

    def _get_takeoff_readiness(self, operation: str) -> dict[str, Any]:
        if self._store is None:
            return {
                "available": False,
                "operation": TakeoffOperation.UNKNOWN.value,
                **_readiness_result(
                    ReadinessReport(status=ReadinessStatus.UNKNOWN, items=())
                ),
            }
        state = self._state
        requested = TakeoffOperation(operation)
        selected = self._store.ground_ops.resolve_operation(state, requested)
        report = self._store.ground_ops.takeoff_readiness(
            state,
            self._store.checklist_engine,
            operation=requested,
        )
        return {
            "available": state.connected,
            "operation": selected.value,
            **_readiness_result(report),
        }

    def _get_flight_status(self) -> dict[str, Any]:
        state = self._state
        if self._store is None:
            snapshot: FlightOpsSnapshot | None = None
        else:
            snapshot = self._store.flight_ops.evaluate(state)
        issue_result = self._get_active_issues()
        issues = issue_result["issues"]
        severity_rank = {"INFO": 0, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 3}
        highest = max(
            (issue["severity"] for issue in issues),
            key=severity_rank.__getitem__,
            default=None,
        )
        telemetry = state.telemetry()
        return {
            "available": snapshot.available if snapshot is not None else False,
            "aircraft": state.aircraft,
            "flight_phase": (
                state.flight_phase.value
                if state.flight_phase is not FlightPhase.UNKNOWN
                else None
            ),
            "flight_stage": snapshot.stage.value if snapshot is not None else None,
            "key_state": {
                name: _telemetry_value(telemetry[name])
                for name in (
                    "indicated_airspeed",
                    "altitude_msl",
                    "heading",
                    "fuel_quantity",
                )
            },
            "issues_coverage": issue_result["coverage"],
            "active_issue_count": len(issues),
            "highest_issue_severity": highest,
            "departure_cleanup": _readiness_result(
                snapshot.departure_cleanup
                if snapshot is not None
                else ReadinessReport(ReadinessStatus.UNKNOWN, ())
            ),
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
        definition = self._store.checklist_engine.definitions[checklist_id]
        active_stage = stage or definition.default_stage or definition.stages[0].id
        return {"started": True, "checklist_id": checklist_id, "stage": active_stage}

    def _advance_guided_checklist(self) -> dict[str, Any]:
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


def _readiness_item(item: ReadinessItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "label": item.label,
        "status": item.status.value,
        "expected": _json_value(item.expected),
        "actual": _json_value(item.actual),
        "reason": item.reason,
    }


def _readiness_result(report: ReadinessReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "blocking_items": [_readiness_item(item) for item in report.blocking_items],
        "unknown_items": [_readiness_item(item) for item in report.unknown_items],
    }


def _ground_ops_result(snapshot: GroundOpsSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        unavailable = {"status": "UNKNOWN", "blocking_items": [], "unknown_items": []}
        return {
            "available": False,
            "phase": "UNKNOWN",
            "lineup_state": "UNCONFIRMED",
            "takeoff_operation": "UNKNOWN",
            "before_taxi": unavailable,
            "takeoff": unavailable.copy(),
        }
    return {
        "available": snapshot.available,
        "phase": snapshot.phase.value,
        "lineup_state": snapshot.lineup_state.value,
        "takeoff_operation": snapshot.takeoff_operation.value,
        "before_taxi": _readiness_result(snapshot.before_taxi),
        "takeoff": _readiness_result(snapshot.takeoff),
    }


def _hornet_knowledge_result(card: HornetKnowledgeCard) -> dict[str, Any]:
    source = card.source
    return {
        "available": True,
        "corpus_version": HORNET_KNOWLEDGE_VERSION,
        "card": {
            "id": card.id,
            "topic": card.topic.value,
            "title": card.title,
            "aircraft": card.aircraft,
            "applicability": card.applicability,
            "summary": card.summary,
            "steps": list(card.steps),
            "cautions": list(card.cautions),
            "source": {
                "publisher": source.publisher,
                "title": source.title,
                "section": source.section,
                "pages": source.pages,
                "url": source.url,
                "document_sha256": source.document_sha256,
                "document_created_at": source.document_created_at,
                "reviewed_on": source.reviewed_on,
            },
        },
    }
