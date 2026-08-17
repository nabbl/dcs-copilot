"""Shared lifecycle contract for deterministic Coach exercises."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..models import OwnshipState, ReferenceObject, ReferenceObjectType

MAX_EXERCISE_SAMPLES = 100_000


class ExerciseId(StrEnum):
    LEFT_ECHELON = "LEFT_ECHELON"
    RIGHT_ECHELON = "RIGHT_ECHELON"
    CASE1_PATTERN = "CASE1_PATTERN"
    CARRIER_APPROACH = "CARRIER_APPROACH"


class ExerciseState(StrEnum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    UNAVAILABLE = "UNAVAILABLE"


class ExerciseUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExerciseStatus:
    exercise: ExerciseId | None
    state: ExerciseState
    reason: str | None = None
    started_at: float | None = None


@dataclass(frozen=True, slots=True)
class CoachFeedback:
    code: str
    message: str
    timestamp: float
    data: dict[str, Any]


class CoachExercise:
    id: ExerciseId
    reference_type: ReferenceObjectType

    def __init__(self, *, started_at: float) -> None:
        self.started_at = started_at
        self.state = ExerciseState.ACTIVE
        self.reason: str | None = None

    @property
    def status(self) -> ExerciseStatus:
        return ExerciseStatus(self.id, self.state, self.reason, self.started_at)

    def update(
        self,
        ownship: OwnshipState,
        reference: ReferenceObject,
        *,
        now: float,
    ) -> tuple[CoachFeedback, ...]:
        return ()

    def stop(self, *, now: float, reason: str | None = None) -> dict[str, Any]:
        self.state = ExerciseState.STOPPED
        self.reason = reason
        return {"exercise": self.id.value, "ended_at": now}

    def mark_unavailable(self, reason: str) -> None:
        self.state = ExerciseState.UNAVAILABLE
        self.reason = reason


class PendingSpatialExercise(CoachExercise):
    def __init__(
        self,
        exercise_id: ExerciseId,
        reference_type: ReferenceObjectType,
        *,
        started_at: float,
    ) -> None:
        super().__init__(started_at=started_at)
        self.id = exercise_id
        self.reference_type = reference_type
