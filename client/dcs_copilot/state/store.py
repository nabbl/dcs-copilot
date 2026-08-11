"""Orchestrates aircraft normalization, history, and phase detection."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dcs_copilot.aircraft.base import AircraftAdapter
from dcs_copilot.aircraft.fa18c import FA18CAdapter
from dcs_copilot.aircraft.generic import GenericAircraftAdapter
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_protocol import FrameComplete
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.events import EventManager, SpeechPolicy
from dcs_copilot.checklists import ChecklistEngine, fa18c_checklists
from dcs_copilot.habits import FlightStatsManager
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import fa18c_rules

from .history import StateHistory
from .models import AircraftState, FlightPhase, TelemetryStatus, TelemetryValue
from .phase_detector import FlightPhaseDetector


@dataclass(frozen=True, slots=True)
class NormalizedStateChange:
    field: str
    old_value: Any
    new_value: Any
    status: TelemetryStatus


class AircraftStateStore:
    def __init__(
        self,
        registry: DcsBiosControlRegistry,
        *,
        client: DcsBiosClient | None = None,
        bios_state: DcsBiosState | None = None,
        value_stale_timeout: float = 30.0,
        history: StateHistory | None = None,
        phase_detector: FlightPhaseDetector | None = None,
        rule_engine: RuleEngine | None = None,
        checklist_engine: ChecklistEngine | None = None,
        event_manager: EventManager | None = None,
        flight_stats: FlightStatsManager | None = None,
        speech_policy: SpeechPolicy | None = None,
        adapters: list[AircraftAdapter] | None = None,
    ) -> None:
        self.registry = registry
        self.client = client
        self.bios_state = client.state if client is not None else bios_state
        self.value_stale_timeout = value_stale_timeout
        self.history = history or StateHistory()
        self.phase_detector = phase_detector or FlightPhaseDetector()
        self.rule_engine = rule_engine or RuleEngine(fa18c_rules())
        self.checklist_engine = checklist_engine or ChecklistEngine(fa18c_checklists())
        if event_manager is not None and speech_policy is not None:
            raise ValueError("pass either event_manager or speech_policy, not both")
        if event_manager is not None and event_manager.rule_engine is not self.rule_engine:
            raise ValueError("event_manager must observe this store's rule_engine")
        self.event_manager = event_manager or EventManager(
            self.rule_engine,
            speech_policy=speech_policy,
        )
        if flight_stats is not None and flight_stats.rule_engine is not self.rule_engine:
            raise ValueError("flight_stats must observe this store's rule_engine")
        self.flight_stats = flight_stats or FlightStatsManager(self.rule_engine)
        self.generic_adapter = GenericAircraftAdapter(registry)
        selected_adapters = adapters or [FA18CAdapter(registry)]
        self._adapters = {
            aircraft_name: adapter
            for adapter in selected_adapters
            for aircraft_name in adapter.aircraft_names
        }
        self.current = AircraftState()
        self._callbacks: list[Callable[[NormalizedStateChange], None]] = []
        if client is not None:
            client.add_frame_callback(self._on_frame)
            client.add_connection_callback(self._on_connection)

    def add_change_callback(
        self, callback: Callable[[NormalizedStateChange], None]
    ) -> None:
        self._callbacks.append(callback)

    def update(
        self,
        *,
        connected: bool,
        aircraft: str | None,
        now: float | None = None,
    ) -> AircraftState:
        timestamp = time.monotonic() if now is None else now
        previous = self.current
        if not connected or self.bios_state is None:
            self.flight_stats.observe(AircraftState(aircraft=aircraft, connected=False))
            self.current = AircraftState(aircraft=aircraft, connected=False)
            self.history.clear()
            self.phase_detector.reset()
            self.rule_engine.reset(now=timestamp)
            self._emit_changes(previous, self.current)
            return self.current

        state = AircraftState(aircraft=aircraft, connected=True)
        adapter = self._adapters.get(aircraft or "", self.generic_adapter)
        partial = adapter.normalize(
            self.bios_state,
            now=timestamp,
            stale_timeout=self.value_stale_timeout,
        )
        partial.apply_to(state)
        self.history.record(state, timestamp=timestamp)
        state.flight_phase = self.phase_detector.update(
            state, self.history, now=timestamp
        )
        self._derive_context_fields(state, timestamp)
        self.history.record(state, timestamp=timestamp)
        self.current = state
        self.flight_stats.observe(state)
        self.rule_engine.evaluate(state, self.history, now=timestamp)
        self._emit_changes(previous, state)
        return state

    def refresh(self, *, now: float | None = None) -> AircraftState:
        if self.client is None:
            return self.current
        return self.update(
            connected=self.client.connected,
            aircraft=self.client.current_aircraft,
            now=now,
        )

    def _on_frame(self, _frame: FrameComplete) -> None:
        self.refresh()

    def _on_connection(self, connected: bool) -> None:
        if not connected:
            self.refresh()

    def _emit_changes(self, previous: AircraftState, current: AircraftState) -> None:
        if previous.aircraft != current.aircraft:
            aircraft_change = NormalizedStateChange(
                "aircraft",
                previous.aircraft,
                current.aircraft,
                TelemetryStatus.AVAILABLE
                if current.aircraft is not None
                else TelemetryStatus.UNAVAILABLE,
            )
            for callback in tuple(self._callbacks):
                callback(aircraft_change)
        if previous.connected != current.connected:
            connection_change = NormalizedStateChange(
                "connected",
                previous.connected,
                current.connected,
                TelemetryStatus.AVAILABLE
                if current.connected
                else TelemetryStatus.UNAVAILABLE,
            )
            for callback in tuple(self._callbacks):
                callback(connection_change)
        if previous.flight_phase != current.flight_phase:
            phase_change = NormalizedStateChange(
                "flight_phase",
                previous.flight_phase,
                current.flight_phase,
                TelemetryStatus.AVAILABLE
                if current.connected
                else TelemetryStatus.UNAVAILABLE,
            )
            for callback in tuple(self._callbacks):
                callback(phase_change)
        previous_values = previous.telemetry()
        for name, value in current.telemetry().items():
            old = previous_values.get(name)
            if (
                old is not None
                and old.value == value.value
                and old.status == value.status
            ):
                continue
            change = NormalizedStateChange(
                name,
                old.value if old is not None else None,
                value.value,
                value.status,
            )
            for callback in tuple(self._callbacks):
                callback(change)

    @staticmethod
    def _derive_context_fields(state: AircraftState, timestamp: float) -> None:
        if state.aircraft != "FA-18C_hornet":
            return
        if not state.weight_on_wheels.usable:
            return
        airborne = not bool(state.weight_on_wheels.value)
        state.airborne = TelemetryValue(
            value=airborne,
            available=True,
            updated_at=state.weight_on_wheels.updated_at,
            source="derived:weight_on_wheels",
            stale=state.weight_on_wheels.stale,
        )
        carrier_launch_available = (
            state.weight_on_wheels.usable and state.launch_bar_deployed.usable
        )
        state.carrier_launch_sequence = TelemetryValue(
            value=bool(state.weight_on_wheels.value)
            and bool(state.launch_bar_deployed.value)
            if carrier_launch_available
            else None,
            available=carrier_launch_available,
            updated_at=timestamp,
            source="derived:carrier_launch_sequence",
        )
        takeoff_available = state.indicated_airspeed.usable or carrier_launch_available
        state.takeoff_sequence = TelemetryValue(
            value=(
                bool(state.carrier_launch_sequence.value)
                if state.carrier_launch_sequence.usable
                else False
            )
            or (
                bool(state.weight_on_wheels.value)
                and state.indicated_airspeed.usable
                and float(state.indicated_airspeed.value) >= 80
            ),
            available=takeoff_available,
            updated_at=timestamp,
            source="derived:takeoff_sequence",
        )
        recovery_signal_available = (
            state.hook_commanded_down.usable or state.hook_position.usable
        )
        recovery_phase = state.flight_phase in {FlightPhase.APPROACH, FlightPhase.LANDING}
        state.carrier_recovery = TelemetryValue(
            value=recovery_phase
            and (
                (state.hook_commanded_down.usable and bool(state.hook_commanded_down.value))
                or (state.hook_position.usable and bool(state.hook_position.value))
            )
            if recovery_signal_available
            else None,
            available=recovery_signal_available,
            updated_at=timestamp,
            source="derived:carrier_recovery",
        )
