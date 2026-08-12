"""Convert deterministic rule transitions into bounded semantic events."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from enum import Enum
from typing import Any
from uuid import uuid4

from ..rules.base import RuleTransition, RuleTransitionType
from ..rules.engine import RuleEngine
from .models import CloudAircraftEvent, CloudManagedEvent
from .policy import SpeechPolicy


class EventManager:
    def __init__(
        self,
        rule_engine: RuleEngine,
        *,
        speech_policy: SpeechPolicy | None = None,
        history_size: int = 256,
    ) -> None:
        if history_size <= 0:
            raise ValueError("event history size must be greater than zero")
        self.rule_engine = rule_engine
        self.speech_policy = speech_policy or SpeechPolicy()
        self._history: deque[CloudManagedEvent] = deque(maxlen=history_size)
        self._callbacks: list[Callable[[CloudManagedEvent], None]] = []
        self._active_event_ids: dict[str, str] = {}
        self._published_event_ids: set[str] = set()
        rule_engine.add_transition_callback(self.handle_transition)

    @property
    def history(self) -> tuple[CloudManagedEvent, ...]:
        return tuple(self._history)

    def add_callback(self, callback: Callable[[CloudManagedEvent], None]) -> None:
        self._callbacks.append(callback)

    def reset(self, *, clear_history: bool = True) -> None:
        self._active_event_ids.clear()
        self._published_event_ids.clear()
        if clear_history:
            self._history.clear()

    def handle_transition(self, transition: RuleTransition) -> None:
        issue = transition.issue
        if transition.type is RuleTransitionType.ACTIVATED:
            event_id = str(uuid4())
            self._active_event_ids[issue.rule_id] = event_id
            status = "RAISED"
            publish = self.speech_policy.allows(transition)
            if publish:
                self._published_event_ids.add(event_id)
            speak = publish
        else:
            event_id = (
                self._active_event_ids.pop(issue.rule_id)
                if issue.rule_id in self._active_event_ids
                else str(uuid4())
            )
            status = transition.type.value
            publish = event_id in self._published_event_ids
            self._published_event_ids.discard(event_id)
            speak = False
        event = CloudAircraftEvent(
            event_id=event_id,
            rule_id=issue.rule_id,
            status=status,
            severity=issue.severity.value,
            aircraft=issue.aircraft,
            flight_phase=(
                issue.flight_phase.value
                if issue.flight_phase.value != "UNKNOWN"
                else None
            ),
            message=issue.message,
            data=_json_value(issue.data),
        )
        managed = CloudManagedEvent(event, transition.timestamp, publish, speak)
        self._history.append(managed)
        for callback in tuple(self._callbacks):
            callback(managed)


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
