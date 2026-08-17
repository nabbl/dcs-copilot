"""Session-scoped orchestration for capabilities, observations, and exercises."""

from __future__ import annotations

from collections import deque
from typing import Any

from .capabilities import CapabilityManager, CapabilityTransition, DcsCapabilities
from .exercises.base import (
    CoachExercise,
    CoachFeedback,
    ExerciseId,
    ExerciseState,
    ExerciseStatus,
    ExerciseUnavailable,
)
from .exercises.carrier_approach import (
    CarrierApproachExercise,
    default_hornet_carrier_profile,
)
from .exercises.case1 import Case1Exercise, default_case1_profile
from .exercises.formation import FormationExercise, default_echelon_profile
from .models import (
    OwnshipState,
    ReferenceObject,
    ReferenceObjectType,
    RelativeObservation,
    TelemetrySource,
)
from .providers.live import LiveObservationStore

_REQUIRED_REFERENCE = {
    ExerciseId.LEFT_ECHELON: ReferenceObjectType.LEAD_AIRCRAFT,
    ExerciseId.RIGHT_ECHELON: ReferenceObjectType.LEAD_AIRCRAFT,
    ExerciseId.CASE1_PATTERN: ReferenceObjectType.CARRIER,
    ExerciseId.CARRIER_APPROACH: ReferenceObjectType.CARRIER,
}


class CoachCoordinator:
    def __init__(self) -> None:
        self.capabilities = CapabilityManager()
        self.observations = LiveObservationStore(self.capabilities)
        self.active: CoachExercise | None = None
        self._last_status = ExerciseStatus(None, ExerciseState.IDLE)
        self._feedback: deque[CoachFeedback] = deque(maxlen=64)
        self._relative: deque[RelativeObservation] = deque(maxlen=2_000)
        self.last_debrief: dict[str, Any] | None = None
        self.capabilities.add_change_callback(self._capabilities_changed)

    @property
    def relative_observations(self) -> tuple[RelativeObservation, ...]:
        return tuple(self._relative)

    def update_capabilities(self, capabilities: DcsCapabilities) -> None:
        self.capabilities.update(capabilities)

    def start(self, exercise: ExerciseId | str, *, now: float) -> ExerciseStatus:
        parsed = ExerciseId(exercise)
        if not self._available(parsed):
            raise ExerciseUnavailable(
                "Spatial coaching isn't available because world-object export is disabled."
            )
        reference_type = _REQUIRED_REFERENCE[parsed]
        reference = self.observations.get_reference(reference_type, now=now)
        if reference is None:
            raise ExerciseUnavailable(
                f"No current {reference_type.value.lower()} reference is available."
            )
        if self.active is not None:
            self.last_debrief = self.active.stop(now=now, reason="replaced")
        self._relative.clear()
        self._feedback.clear()
        self.active = self._create_exercise(parsed, now=now)
        ownship = self.observations.ownship
        if ownship is not None:
            self._update_active(ownship, reference, now=now)
        self._last_status = self.active.status
        return self._last_status

    def stop(self, *, now: float) -> ExerciseStatus:
        if self.active is None:
            return self._last_status
        self.last_debrief = self.active.stop(now=now)
        self._last_status = self.active.status
        self.active = None
        return self._last_status

    def status(self) -> ExerciseStatus:
        return self.active.status if self.active is not None else self._last_status

    def feedback(self) -> tuple[CoachFeedback, ...]:
        return tuple(self._feedback)

    def ingest(
        self,
        ownship: OwnshipState,
        references: list[ReferenceObject],
        *,
        now: float,
        source: TelemetrySource = TelemetrySource.DCS_EXPORT,
    ) -> tuple[CoachFeedback, ...]:
        self.observations.update_ownship(ownship)
        self.observations.replace_references(references, source=source)
        if self.active is None:
            return ()
        reference = self.observations.get_reference(
            self.active.reference_type,
            now=now,
        )
        if reference is None:
            self.active.state = ExerciseState.PAUSED
            self.active.reason = "Waiting for the selected reference object."
            return ()
        return self._update_active(ownship, reference, now=now)

    def _update_active(
        self,
        ownship: OwnshipState,
        reference: ReferenceObject,
        *,
        now: float,
    ) -> tuple[CoachFeedback, ...]:
        assert self.active is not None
        feedback = self.active.update(ownship, reference, now=now)
        self._feedback.extend(feedback)
        last_sample = getattr(self.active, "last_sample", None)
        relative = getattr(last_sample, "relative", None)
        if isinstance(relative, RelativeObservation):
            self._relative.append(relative)
        return feedback

    def reset(self) -> None:
        self.observations.clear()
        self.active = None
        self._relative.clear()
        self._feedback.clear()
        self._last_status = ExerciseStatus(None, ExerciseState.IDLE)

    def _available(self, exercise: ExerciseId) -> bool:
        coach = self.capabilities.coach
        if exercise in {ExerciseId.LEFT_ECHELON, ExerciseId.RIGHT_ECHELON}:
            return coach.formation_coaching
        if exercise is ExerciseId.CASE1_PATTERN:
            return coach.carrier_pattern_coaching
        return coach.carrier_approach_geometry

    @staticmethod
    def _create_exercise(exercise: ExerciseId, *, now: float) -> CoachExercise:
        if exercise in {ExerciseId.LEFT_ECHELON, ExerciseId.RIGHT_ECHELON}:
            return FormationExercise(
                default_echelon_profile(exercise),
                started_at=now,
                exercise_id=exercise,
            )
        if exercise is ExerciseId.CARRIER_APPROACH:
            return CarrierApproachExercise(
                default_hornet_carrier_profile(),
                started_at=now,
            )
        return Case1Exercise(default_case1_profile(), started_at=now)

    def _capabilities_changed(self, transition: CapabilityTransition) -> None:
        if self.active is None:
            return
        was_available = self._exercise_available(
            self.active.id, transition.previous_coach
        )
        is_available = self._exercise_available(
            self.active.id, transition.current_coach
        )
        if not was_available or is_available:
            return
        exercise_id = self.active.id
        reason = (
            "World-object export permission was removed."
            if transition.world_object_export_lost
            else "Required ownship export became unavailable."
        )
        self.active.mark_unavailable(reason)
        self._last_status = ExerciseStatus(
            exercise_id,
            ExerciseState.UNAVAILABLE,
            reason,
            self.active.started_at,
        )
        self.active = None
        self._relative.clear()

    @staticmethod
    def _exercise_available(exercise: ExerciseId, capabilities) -> bool:
        if exercise in {ExerciseId.LEFT_ECHELON, ExerciseId.RIGHT_ECHELON}:
            return capabilities.formation_coaching
        if exercise is ExerciseId.CASE1_PATTERN:
            return capabilities.carrier_pattern_coaching
        return capabilities.carrier_approach_geometry
