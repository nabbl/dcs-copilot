"""Aircraft-independent deterministic checklist evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..rules.base import RuleContext
from ..rules.declarative import evaluate_condition
from ..state.history import StateHistory
from ..state.models import AircraftState
from .models import (
    ChecklistDefinition,
    ChecklistItem,
    ChecklistItemResult,
    ChecklistItemStatus,
    ChecklistResult,
    ChecklistSession,
    ChecklistStage,
    VerificationSource,
    VerificationType,
)


@dataclass(frozen=True, slots=True)
class ChecklistCapability:
    checklist_id: str
    aircraft: str
    stages: tuple[str, ...]


class ChecklistEngine:
    def __init__(self, definitions: Iterable[ChecklistDefinition]) -> None:
        self.definitions = {definition.id: definition for definition in definitions}
        self._validate_definitions()
        self.session = ChecklistSession()
        self._latched_item_results: dict[tuple[str, str], ChecklistItemResult] = {}

    def _validate_definitions(self) -> None:
        for definition in self.definitions.values():
            stage_ids: set[str] = set()
            definition_item_ids: set[str] = set()
            for stage in definition.stages:
                if stage.id in stage_ids:
                    raise ValueError(f"duplicate stage id: {stage.id}")
                stage_ids.add(stage.id)
                item_ids: set[str] = set()
                for item in stage.items:
                    if item.id in item_ids:
                        raise ValueError(f"duplicate item id: {item.id}")
                    if item.id in definition_item_ids:
                        raise ValueError(
                            f"duplicate item id across checklist stages: {item.id}"
                        )
                    item_ids.add(item.id)
                    definition_item_ids.add(item.id)
            for stage in definition.stages:
                for dependency_id in stage.depends_on:
                    if dependency_id not in stage_ids:
                        raise ValueError(f"unknown dependency: {dependency_id}")
            if (
                definition.default_stage is not None
                and definition.default_stage not in stage_ids
            ):
                raise ValueError(f"unknown dependency: {definition.default_stage}")
            for stage in definition.stages:
                self._stage_chain(definition, stage)

    def capabilities(self) -> tuple[ChecklistCapability, ...]:
        return tuple(
            ChecklistCapability(
                checklist_id=definition.id,
                aircraft=definition.aircraft,
                stages=tuple(stage.id for stage in definition.stages),
            )
            for definition in self.definitions.values()
        )

    def evaluate(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
        checklist_id: str | None = None,
        stage_id: str | None = None,
    ) -> ChecklistResult:
        definition = self._definition_for(state, checklist_id)
        stage = self._stage_for(definition, stage_id or self.session.stage_id)
        evaluated: dict[str, ChecklistItemResult] = {}
        for selected_stage in self._stage_chain(definition, stage):
            for item in selected_stage.items:
                confirmed_at = self.session.pilot_confirmed_items.get(item.id)
                evaluated[item.id] = (
                    _pilot_confirmed_result(item, confirmed_at)
                    if confirmed_at is not None
                    else self._latched_item_results.get((definition.id, item.id))
                    or self._evaluate_item(item, state, history, now=now)
                )
        results = tuple(evaluated.values())
        complete = tuple(
            item for item in results if item.status is ChecklistItemStatus.COMPLETE
        )
        incomplete = tuple(
            item for item in results if item.status is ChecklistItemStatus.INCOMPLETE
        )
        unconfirmed = tuple(
            item for item in results if item.status is ChecklistItemStatus.UNCONFIRMED
        )
        not_applicable = tuple(
            item
            for item in results
            if item.status is ChecklistItemStatus.NOT_APPLICABLE
        )
        return ChecklistResult(
            checklist_id=definition.id,
            aircraft=definition.aircraft,
            stage=stage.id,
            complete=not incomplete and not unconfirmed,
            complete_items=complete,
            incomplete_items=incomplete,
            unconfirmed_items=unconfirmed,
            not_applicable_items=not_applicable,
        )

    def missing(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
        checklist_id: str | None = None,
        stage_id: str | None = None,
    ) -> tuple[ChecklistItemResult, ...]:
        result = self.evaluate(
            state,
            history,
            now=now,
            checklist_id=checklist_id,
            stage_id=stage_id,
        )
        return (*result.incomplete_items, *result.unconfirmed_items)

    def start(self, checklist_id: str, stage_id: str | None = None) -> None:
        definition = self.definitions.get(checklist_id)
        if definition is None:
            raise ValueError(f"unknown checklist: {checklist_id}")
        selected_stage = (
            self._stage_for(definition, stage_id)
            if stage_id is not None
            else self._stage_for(definition, definition.default_stage)
        )
        self.session.start(checklist_id, selected_stage.id)

    def stop(self) -> None:
        self.session.stop()

    def reset(self) -> None:
        self.session.reset()
        self._latched_item_results.clear()

    def observe(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> None:
        """Latch only items explicitly defined as historical observations."""

        for definition in self.definitions.values():
            if definition.aircraft != state.aircraft:
                continue
            for stage in definition.stages:
                for item in stage.items:
                    key = (definition.id, item.id)
                    if not item.latch_completion or key in self._latched_item_results:
                        continue
                    result = self._evaluate_item(item, state, history, now=now)
                    if result.status is ChecklistItemStatus.COMPLETE:
                        self._latched_item_results[key] = result

    def confirm_manual_item(self, item_id: str) -> None:
        if not item_id.strip():
            raise ValueError("manual checklist item id is required")
        checklist_id = self.session.checklist_id
        if checklist_id is None:
            raise ValueError("no guided checklist is active")
        definition = self.definitions[checklist_id]
        item = next(
            (
                candidate
                for stage in definition.stages
                for candidate in stage.items
                if candidate.id == item_id
            ),
            None,
        )
        if item is None:
            raise ValueError(f"unknown checklist item: {item_id}")
        if item.verification is not VerificationType.MANUAL:
            raise ValueError(f"checklist item is not manually confirmable: {item_id}")
        self.session.pilot_confirmed_items[item_id] = 0.0

    def confirm_current_item(
        self,
        item_id: str,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> tuple[ChecklistItemResult, bool]:
        """Confirm only the current guided item from an explicit pilot report."""

        if not item_id.strip():
            raise ValueError("checklist item id is required")
        current = self.next_item(state, history, now=now)
        if current is None:
            raise ValueError("the guided checklist has no unresolved item")
        if current.id != item_id:
            raise ValueError(
                f"only the current guided checklist item can be confirmed: {current.id}"
            )
        self.session.pilot_confirmed_items[item_id] = now
        overridden = current.verification_type is not VerificationType.MANUAL
        return current, overridden

    def manual_item_confirmed(self, item_id: str) -> bool:
        return item_id in self.session.pilot_confirmed_items

    def next_item(
        self,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> ChecklistItemResult | None:
        if self.session.checklist_id is None or self.session.stage_id is None:
            raise ValueError("no guided checklist is active")
        result = self.evaluate(
            state,
            history,
            now=now,
            checklist_id=self.session.checklist_id,
            stage_id=self.session.stage_id,
        )
        unresolved = (*result.incomplete_items, *result.unconfirmed_items)
        return unresolved[0] if unresolved else None

    def explain_item(
        self,
        item_id: str,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
        checklist_id: str | None = None,
        stage_id: str | None = None,
    ) -> ChecklistItemResult:
        result = self.evaluate(
            state,
            history,
            now=now,
            checklist_id=checklist_id,
            stage_id=stage_id,
        )
        for item in result.items:
            if item.id == item_id:
                return item
        raise ValueError(f"unknown checklist item in selected stage: {item_id}")

    def _definition_for(
        self, state: AircraftState, checklist_id: str | None
    ) -> ChecklistDefinition:
        requested = checklist_id or self.session.checklist_id
        if requested is not None:
            definition = self.definitions.get(requested)
            if definition is None:
                raise ValueError(f"unknown checklist: {requested}")
            return definition
        for definition in self.definitions.values():
            if definition.aircraft == state.aircraft:
                return definition
        raise ValueError("no checklist is available for the current aircraft")

    @staticmethod
    def _stage_for(
        definition: ChecklistDefinition, stage_id: str | None
    ) -> ChecklistStage:
        if stage_id is None:
            stage_id = definition.default_stage
        if stage_id is None:
            return definition.stages[0]
        for stage in definition.stages:
            if stage.id == stage_id:
                return stage
        raise ValueError(f"unknown checklist stage: {stage_id}")

    @classmethod
    def _stage_chain(
        cls,
        definition: ChecklistDefinition,
        target: ChecklistStage,
    ) -> tuple[ChecklistStage, ...]:
        selected: list[ChecklistStage] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(stage: ChecklistStage) -> None:
            if stage.id in visited:
                return
            if stage.id in visiting:
                raise ValueError(f"cyclic checklist stage dependency: {stage.id}")
            visiting.add(stage.id)
            for dependency_id in stage.depends_on:
                dependency = cls._stage_for(definition, dependency_id)
                visit(dependency)
            visiting.remove(stage.id)
            visited.add(stage.id)
            selected.append(stage)

        visit(target)
        return tuple(selected)

    def _evaluate_item(
        self,
        item: ChecklistItem,
        state: AircraftState,
        history: StateHistory,
        *,
        now: float,
    ) -> ChecklistItemResult:
        context = RuleContext(state=state, history=history, now=now, active=False)
        if item.applicable_if is not None and not evaluate_condition(
            item.applicable_if, context
        ):
            return _result(
                item,
                ChecklistItemStatus.NOT_APPLICABLE,
                None,
                None,
                "item is not applicable in the current configuration",
            )
        if item.verification is VerificationType.STATE:
            return self._evaluate_state(item, state)
        if item.verification is VerificationType.DERIVED:
            if item.condition is None:
                return _result(
                    item,
                    ChecklistItemStatus.UNCONFIRMED,
                    None,
                    None,
                    "derived item has no condition",
                )
            status = (
                ChecklistItemStatus.COMPLETE
                if evaluate_condition(item.condition, context)
                else ChecklistItemStatus.INCOMPLETE
            )
            return _result(
                item,
                status,
                "condition true",
                _condition_actual(item.condition, state),
                "derived condition is satisfied"
                if status is ChecklistItemStatus.COMPLETE
                else "derived condition is not satisfied",
            )
        if item.verification is VerificationType.ACTION:
            return self._evaluate_action(item, history, now=now)
        if item.verification is VerificationType.MANUAL:
            status = (
                ChecklistItemStatus.COMPLETE
                if item.id in self.session.pilot_confirmed_items
                else ChecklistItemStatus.UNCONFIRMED
            )
            return _result(
                item,
                status,
                "pilot confirmation",
                "confirmed" if status is ChecklistItemStatus.COMPLETE else None,
                "pilot confirmed this manual checklist item"
                if status is ChecklistItemStatus.COMPLETE
                else "manual checklist item requires pilot confirmation",
            )
        raise AssertionError(f"unhandled verification type: {item.verification}")

    @staticmethod
    def _evaluate_state(
        item: ChecklistItem,
        state: AircraftState,
    ) -> ChecklistItemResult:
        expected = item.expected or {}
        field = expected.get("field")
        if not isinstance(field, str):
            return _result(
                item,
                ChecklistItemStatus.UNCONFIRMED,
                expected,
                None,
                "state item has no expected field",
            )
        telemetry = state.telemetry().get(field)
        if telemetry is None or not telemetry.available:
            return _result(
                item,
                ChecklistItemStatus.UNCONFIRMED,
                expected,
                None,
                f"{field} is unavailable",
            )
        actual = telemetry.value
        if not telemetry.usable:
            return _result(
                item,
                ChecklistItemStatus.UNCONFIRMED,
                expected,
                actual,
                f"{field} is stale",
                observed_at=telemetry.updated_at,
            )
        if "equals" in expected:
            passed = _values_equal(actual, expected["equals"])
            reason = (
                f"{field} matches expected value"
                if passed
                else f"{field} is {actual}, expected {expected['equals']}"
            )
            return _result(
                item,
                ChecklistItemStatus.COMPLETE
                if passed
                else ChecklistItemStatus.INCOMPLETE,
                expected["equals"],
                actual,
                reason,
                observed_at=telemetry.updated_at,
            )
        if "not_equals" in expected:
            passed = not _values_equal(actual, expected["not_equals"])
            return _result(
                item,
                ChecklistItemStatus.COMPLETE
                if passed
                else ChecklistItemStatus.INCOMPLETE,
                f"not {expected['not_equals']}",
                actual,
                f"{field} is acceptable"
                if passed
                else f"{field} must not be {expected['not_equals']}",
                observed_at=telemetry.updated_at,
            )
        if "one_of" in expected:
            allowed = tuple(expected["one_of"])
            passed = any(_values_equal(actual, value) for value in allowed)
            return _result(
                item,
                ChecklistItemStatus.COMPLETE
                if passed
                else ChecklistItemStatus.INCOMPLETE,
                allowed,
                actual,
                f"{field} is an accepted value"
                if passed
                else f"{field} is not one of the accepted values",
                observed_at=telemetry.updated_at,
            )
        if "less_than_or_equal" in expected:
            target = float(expected["less_than_or_equal"])
            passed = isinstance(actual, (int, float)) and float(actual) <= target
            return _result(
                item,
                ChecklistItemStatus.COMPLETE
                if passed
                else ChecklistItemStatus.INCOMPLETE,
                f"<= {target:g}",
                actual,
                f"{field} is within limit"
                if passed
                else f"{field} is above {target:g}",
                observed_at=telemetry.updated_at,
            )
        if "greater_than" in expected:
            target = float(expected["greater_than"])
            passed = isinstance(actual, (int, float)) and float(actual) > target
            return _result(
                item,
                ChecklistItemStatus.COMPLETE
                if passed
                else ChecklistItemStatus.INCOMPLETE,
                f"> {target:g}",
                actual,
                f"{field} is above {target:g}"
                if passed
                else f"{field} is not above {target:g}",
                observed_at=telemetry.updated_at,
            )
        return _result(
            item,
            ChecklistItemStatus.UNCONFIRMED,
            expected,
            actual,
            "state item has no supported expectation",
            observed_at=telemetry.updated_at,
        )

    @staticmethod
    def _evaluate_action(
        item: ChecklistItem,
        history: StateHistory,
        *,
        now: float,
    ) -> ChecklistItemResult:
        if item.action_field is None:
            return _result(
                item,
                ChecklistItemStatus.UNCONFIRMED,
                None,
                None,
                "action item has no action field",
            )
        transitions = history.transitions(item.action_field, since=0.0)
        observed = next(
            (
                transition
                for transition in reversed(transitions)
                if transition.new_value is True
            ),
            None,
        )
        if observed is None:
            return _result(
                item,
                ChecklistItemStatus.UNCONFIRMED,
                f"{item.action_field} observed true",
                None,
                "required action has not been observed in this session",
            )
        return _result(
            item,
            ChecklistItemStatus.COMPLETE,
            f"{item.action_field} observed true",
            True,
            "required action was observed in this session",
            observed_at=observed.timestamp,
        )


def _result(
    item: ChecklistItem,
    status: ChecklistItemStatus,
    expected: Any | None,
    actual: Any | None,
    reason: str,
    *,
    observed_at: float | None = None,
    verification_source: VerificationSource | None = None,
) -> ChecklistItemResult:
    return ChecklistItemResult(
        id=item.id,
        label=item.label,
        status=status,
        expected=expected,
        actual=actual,
        reason=reason,
        verification_type=item.verification,
        verification_source=verification_source or _verification_source(item),
        observed_at=observed_at,
    )


def _verification_source(item: ChecklistItem) -> VerificationSource:
    return {
        VerificationType.STATE: VerificationSource.TELEMETRY,
        VerificationType.DERIVED: VerificationSource.DERIVED_TELEMETRY,
        VerificationType.ACTION: VerificationSource.OBSERVED_ACTION,
        VerificationType.MANUAL: VerificationSource.PILOT_CONFIRMATION,
    }[item.verification]


def _pilot_confirmed_result(
    item: ChecklistItem, confirmed_at: float
) -> ChecklistItemResult:
    overridden = item.verification is not VerificationType.MANUAL
    return _result(
        item,
        ChecklistItemStatus.COMPLETE,
        "explicit pilot confirmation",
        "confirmed",
        (
            "pilot explicitly confirmed this item; this overrides checklist telemetry"
            if overridden
            else "pilot explicitly confirmed this manual checklist item"
        ),
        observed_at=confirmed_at,
        verification_source=(
            VerificationSource.PILOT_OVERRIDE
            if overridden
            else VerificationSource.PILOT_CONFIRMATION
        ),
    )


def _values_equal(actual: Any, expected: Any) -> bool:
    if hasattr(actual, "value") and isinstance(expected, str):
        return actual.value == expected
    return actual == expected


def _condition_actual(
    condition: dict[str, Any], state: AircraftState
) -> dict[str, Any]:
    telemetry = state.telemetry()
    fields = [
        field
        for field in condition
        if field not in {"all", "any", "not", "available", "changed_to", "changed_from"}
    ]
    return {
        field: telemetry[field].value
        for field in fields
        if field in telemetry and telemetry[field].available
    }
