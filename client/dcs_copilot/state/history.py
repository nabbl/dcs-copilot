"""Compact, bounded history of meaningful normalized state transitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from .models import AircraftState


@dataclass(frozen=True, slots=True)
class StateTransition:
    field: str
    old_value: Any
    new_value: Any
    timestamp: float


class StateHistory:
    def __init__(
        self,
        retention_seconds: float = 60.0,
        *,
        numeric_thresholds: dict[str, float] | None = None,
    ) -> None:
        self.retention_seconds = retention_seconds
        self.numeric_thresholds = {
            "indicated_airspeed": 1.0,
            "ground_speed": 0.5,
            "altitude_msl": 10.0,
            "heading": 2.0,
            "fuel_quantity": 10.0,
            "speed_brake": 0.02,
            "engine_rpm_left": 1.0,
            "engine_rpm_right": 1.0,
            "throttle_left": 0.02,
            "throttle_right": 0.02,
            **(numeric_thresholds or {}),
        }
        self._transitions: deque[StateTransition] = deque()
        self._last: dict[str, Any] = {}

    def record(
        self, state: AircraftState, *, timestamp: float
    ) -> tuple[StateTransition, ...]:
        added: list[StateTransition] = []
        for name, telemetry in state.telemetry().items():
            current = telemetry.value if telemetry.usable else None
            if name not in self._last:
                self._last[name] = current
                if current is not None:
                    added.append(StateTransition(name, None, current, timestamp))
                continue
            previous = self._last[name]
            if not self._meaningfully_changed(name, previous, current):
                continue
            transition = StateTransition(name, previous, current, timestamp)
            self._transitions.append(transition)
            added.append(transition)
            self._last[name] = current
        for transition in added:
            if transition not in self._transitions:
                self._transitions.append(transition)
        self.prune(timestamp)
        return tuple(added)

    def prune(self, now: float) -> None:
        cutoff = now - self.retention_seconds
        while self._transitions and self._transitions[0].timestamp < cutoff:
            self._transitions.popleft()

    def transitions(
        self, field: str | None = None, *, since: float | None = None
    ) -> tuple[StateTransition, ...]:
        return tuple(
            item
            for item in self._transitions
            if (field is None or item.field == field)
            and (since is None or item.timestamp >= since)
        )

    def changed_within(
        self,
        field: str,
        *,
        old_value: Any,
        new_value: Any,
        seconds: float,
        now: float,
    ) -> bool:
        return any(
            item.old_value == old_value and item.new_value == new_value
            for item in self.transitions(field, since=now - seconds)
        )

    def rate(self, field: str, *, seconds: float, now: float) -> float | None:
        samples = [
            item
            for item in self.transitions(field, since=now - seconds)
            if isinstance(item.new_value, (int, float))
        ]
        if len(samples) < 2:
            return None
        first, last = samples[0], samples[-1]
        elapsed = last.timestamp - first.timestamp
        if elapsed <= 0:
            return None
        return (float(last.new_value) - float(first.new_value)) / elapsed

    def latest_value(self, field: str) -> Any:
        return self._last.get(field)

    def clear(self) -> None:
        self._transitions.clear()
        self._last.clear()

    def _meaningfully_changed(self, field: str, old: Any, new: Any) -> bool:
        if old is None or new is None:
            return bool(old != new)
        threshold = self.numeric_thresholds.get(field)
        if (
            threshold is not None
            and isinstance(old, (int, float))
            and isinstance(new, (int, float))
        ):
            return abs(float(new) - float(old)) >= threshold
        return bool(old != new)
