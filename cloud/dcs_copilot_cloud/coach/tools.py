"""Bounded high-level Coach tools exposed to MARA's conversational layer."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from .coordinator import CoachCoordinator
from .exercises.base import ExerciseId, ExerciseUnavailable


class CoachToolName(StrEnum):
    GET_CAPABILITIES = "coach_get_capabilities"
    START_EXERCISE = "coach_start_exercise"
    STOP_EXERCISE = "coach_stop_exercise"
    GET_STATUS = "coach_get_status"
    GET_FEEDBACK = "coach_get_feedback"
    GET_LAST_DEBRIEF = "coach_get_last_debrief"


COACH_TOOL_NAMES = tuple(item.value for item in CoachToolName)


class CoachToolError(ValueError):
    pass


class CoachToolExecutor:
    def __init__(
        self,
        coach: CoachCoordinator,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.coach = coach
        self.clock = clock

    def execute(
        self, tool: CoachToolName | str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            name = CoachToolName(tool)
        except ValueError as exc:
            raise CoachToolError("unknown Coach tool") from exc
        if not isinstance(arguments, dict):
            raise CoachToolError("Coach tool arguments must be an object")
        if name is CoachToolName.GET_CAPABILITIES:
            _exact(arguments, set())
            capabilities = self.coach.capabilities.coach
            spatial = self.coach.capabilities.dcs.world_object_export
            return {
                "ownship": capabilities.ownship_coaching,
                "formation": capabilities.formation_coaching,
                "case1_pattern": capabilities.carrier_pattern_coaching,
                "carrier_approach": capabilities.carrier_approach_geometry,
                "procedure": capabilities.procedure_coaching,
                "world_object_export": spatial,
                "restriction": (
                    None
                    if spatial
                    else "Spatial coaching is unavailable because world-object export is disabled on this server."
                ),
            }
        if name is CoachToolName.START_EXERCISE:
            _exact(arguments, {"exercise", "reference"}, optional={"reference"})
            exercise = arguments.get("exercise")
            if not isinstance(exercise, str):
                raise CoachToolError("exercise must be a string")
            try:
                parsed = ExerciseId(exercise)
            except ValueError as exc:
                raise CoachToolError("unsupported Coach exercise") from exc
            reference = arguments.get("reference")
            if reference is not None and (
                not isinstance(reference, str) or len(reference) > 128
            ):
                raise CoachToolError("reference must be a short string")
            try:
                status = self.coach.start(parsed, now=self.clock())
            except ExerciseUnavailable as exc:
                return {
                    "available": False,
                    "exercise": parsed.value,
                    "state": "UNAVAILABLE",
                    "reason": str(exc),
                }
            return _status(status) | {"available": True}
        if name is CoachToolName.STOP_EXERCISE:
            _exact(arguments, set())
            return _status(self.coach.stop(now=self.clock()))
        if name is CoachToolName.GET_STATUS:
            _exact(arguments, set())
            return _status(self.coach.status())
        if name is CoachToolName.GET_FEEDBACK:
            _exact(arguments, set())
            return {
                "feedback": [
                    {
                        "code": item.code,
                        "message": item.message,
                        "timestamp": item.timestamp,
                        "data": item.data,
                    }
                    for item in self.coach.feedback()
                ]
            }
        _exact(arguments, set())
        return {"debrief": self.coach.last_debrief}


def _exact(
    arguments: dict[str, Any],
    allowed: set[str],
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    unknown = set(arguments) - allowed
    missing = allowed - optional - set(arguments)
    if unknown:
        raise CoachToolError(
            "unknown Coach tool arguments: " + ", ".join(sorted(unknown))
        )
    if missing:
        raise CoachToolError(
            "missing Coach tool arguments: " + ", ".join(sorted(missing))
        )


def _status(status) -> dict[str, Any]:
    return {
        "exercise": status.exercise.value if status.exercise else None,
        "state": status.state.value,
        "reason": status.reason,
        "started_at": status.started_at,
    }
