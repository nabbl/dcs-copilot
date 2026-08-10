"""JSONL replay of normalized state through phase detection and rules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from dcs_copilot_protocol import FlightSummary

from dcs_copilot.events import EventManager
from dcs_copilot.habits import FlightStatsManager
from dcs_copilot.rules.base import RuleTransition
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import fa18c_rules
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import (
    AircraftState,
    CanopyState,
    FlapState,
    FlightPhase,
    GearState,
    MasterArmState,
    TelemetryValue,
)
from dcs_copilot.state.phase_detector import FlightPhaseDetector

ENUM_FIELDS: dict[str, type[object]] = {
    "gear_position": GearState,
    "flap_position": FlapState,
    "canopy_state": CanopyState,
    "master_arm": MasterArmState,
}


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    timestamp: float
    state: AircraftState
    supplied_phase: FlightPhase | None = None


@dataclass(frozen=True, slots=True)
class ReplayRun:
    frame_count: int
    transitions: tuple[RuleTransition, ...]
    event_count: int
    active_issue_count: int
    final_phase: FlightPhase
    flight_summaries: tuple[FlightSummary, ...] = field(compare=False)


class ReplayPlayer:
    def __init__(
        self,
        *,
        phase_detector: FlightPhaseDetector | None = None,
        rule_engine: RuleEngine | None = None,
        history: StateHistory | None = None,
        event_manager: EventManager | None = None,
    ) -> None:
        self.phase_detector = phase_detector or FlightPhaseDetector()
        self.rule_engine = rule_engine or RuleEngine(fa18c_rules())
        self.event_manager = event_manager or EventManager(self.rule_engine)
        self.flight_stats = FlightStatsManager(self.rule_engine)
        self.history = history or StateHistory()

    def load(self, path: Path) -> tuple[ReplayFrame, ...]:
        frames: list[ReplayFrame] = []
        previous_timestamp: float | None = None
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    payload = json.loads(line)
                    frame = _parse_frame(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"{path}:{line_number}: invalid replay frame: {exc}"
                    ) from exc
                if (
                    previous_timestamp is not None
                    and frame.timestamp < previous_timestamp
                ):
                    raise ValueError(
                        f"{path}:{line_number}: timestamps must be nondecreasing"
                    )
                previous_timestamp = frame.timestamp
                frames.append(frame)
        return tuple(frames)

    def run(self, path: Path) -> ReplayRun:
        transitions: list[RuleTransition] = []
        frames = self.load(path)
        start_time = frames[0].timestamp if frames else 0.0
        self.history.clear()
        self.phase_detector.reset()
        self.rule_engine.reset(now=start_time, emit=False)
        self.event_manager.reset()
        for pending in self.flight_stats.pending:
            self.flight_stats.acknowledge(pending.summary_id)
        for frame in frames:
            state = frame.state
            if not state.connected:
                self.flight_stats.observe(state)
                self.history.clear()
                self.phase_detector.reset()
                transitions.extend(self.rule_engine.reset(now=frame.timestamp))
                continue
            self.history.record(state, timestamp=frame.timestamp)
            state.flight_phase = (
                frame.supplied_phase
                if frame.supplied_phase is not None
                else self.phase_detector.update(
                    state, self.history, now=frame.timestamp
                )
            )
            self.flight_stats.observe(state)
            transitions.extend(
                self.rule_engine.evaluate(state, self.history, now=frame.timestamp)
            )
        self.flight_stats.finish()
        final_phase = frames[-1].state.flight_phase if frames else FlightPhase.UNKNOWN
        return ReplayRun(
            frame_count=len(frames),
            transitions=tuple(transitions),
            event_count=len(self.event_manager.history),
            active_issue_count=len(self.rule_engine.active_issues),
            final_phase=final_phase,
            flight_summaries=self.flight_stats.pending,
        )


def _parse_frame(payload: object) -> ReplayFrame:
    if not isinstance(payload, dict):
        raise TypeError("frame must be a JSON object")
    timestamp = float(payload["timestamp"])
    aircraft = payload.get("aircraft", "FA-18C_hornet")
    if aircraft is not None and not isinstance(aircraft, str):
        raise TypeError("aircraft must be a string or null")
    connected = payload.get("connected", True)
    if not isinstance(connected, bool):
        raise TypeError("connected must be a boolean")
    state = AircraftState(aircraft=aircraft, connected=connected)
    telemetry_names = {
        model_field.name
        for model_field in fields(AircraftState)
        if model_field.name
        not in {"aircraft", "connected", "flight_phase", "warning_lights", "raw"}
    }
    values = payload.get("fields", {})
    if not isinstance(values, dict):
        raise TypeError("fields must be an object")
    unknown = set(values) - telemetry_names
    if unknown:
        raise ValueError(f"unknown normalized fields: {', '.join(sorted(unknown))}")
    for name, encoded in values.items():
        setattr(state, name, _parse_telemetry(name, encoded, timestamp))
    warning_values = payload.get("warning_lights", {})
    if not isinstance(warning_values, dict):
        raise TypeError("warning_lights must be an object")
    state.warning_lights = {
        str(name): _parse_telemetry(f"warning_lights.{name}", value, timestamp)
        for name, value in warning_values.items()
    }
    supplied_phase_raw = payload.get("flight_phase")
    supplied_phase = (
        FlightPhase(str(supplied_phase_raw)) if supplied_phase_raw is not None else None
    )
    return ReplayFrame(timestamp, state, supplied_phase)


def _parse_telemetry(
    field_name: str, encoded: Any, timestamp: float
) -> TelemetryValue[Any]:
    if isinstance(encoded, dict):
        available = encoded.get("available", True)
        stale = encoded.get("stale", False)
        value = encoded.get("value")
        updated_at_raw = encoded.get("updated_at", timestamp)
        source = encoded.get("source", "replay")
        if not isinstance(available, bool) or not isinstance(stale, bool):
            raise TypeError(f"{field_name} availability flags must be booleans")
        updated_at = float(updated_at_raw) if updated_at_raw is not None else None
        if source is not None and not isinstance(source, str):
            raise TypeError(f"{field_name} source must be a string or null")
    else:
        available = encoded is not None
        stale = False
        value = encoded
        updated_at = timestamp if available else None
        source = "replay"
    enum_type = ENUM_FIELDS.get(field_name)
    if enum_type is not None and value is not None:
        value = enum_type(value)  # type: ignore[call-arg]
    return TelemetryValue(
        value=value,
        available=available,
        updated_at=updated_at,
        source=source,
        stale=stale,
    )
