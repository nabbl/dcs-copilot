"""Repeatable synthetic workload for thin-client performance measurements."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TypeVar

from dcs_copilot.dcs.bios_protocol import DcsBiosProtocolParser
from dcs_copilot.events import EventManager
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import fa18c_rules
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import (
    AircraftState,
    CanopyState,
    GearState,
    TelemetryValue,
)
from dcs_copilot.state.phase_detector import FlightPhaseDetector

from .resources import ResourceSnapshot

SYNC = b"\x55\x55\x55\x55"
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ClientBenchmarkResult:
    updates: int
    parser_frames: int
    bytes_processed: int
    idle_wall_seconds: float
    idle_cpu_seconds: float
    idle_cpu_percent: float
    workload_wall_seconds: float
    workload_cpu_seconds: float
    updates_per_second: float
    estimated_cpu_percent_at_30hz: float
    resident_memory_before: int | None
    resident_memory_after: int | None


def run_client_benchmark(
    *, updates: int = 30_000, idle_seconds: float = 1.0
) -> ClientBenchmarkResult:
    if updates <= 0:
        raise ValueError("updates must be greater than zero")
    if idle_seconds < 0:
        raise ValueError("idle_seconds cannot be negative")

    before_idle = ResourceSnapshot.capture()
    time.sleep(idle_seconds)
    after_idle = ResourceSnapshot.capture()

    parser = DcsBiosProtocolParser()
    history = StateHistory()
    detector = FlightPhaseDetector()
    engine = RuleEngine(fa18c_rules())
    EventManager(engine)
    state = _safe_cruise_state()
    packet_size = len(_packet(0))

    before_workload = ResourceSnapshot.capture()
    for update in range(updates + 1):
        parser.feed(_packet(update))
        if update == updates:
            continue
        now = update / 30.0
        history.record(state, timestamp=now)
        state.flight_phase = detector.update(state, history, now=now)
        engine.evaluate(state, history, now=now)
    after_workload = ResourceSnapshot.capture()

    idle_wall = max(0.0, after_idle.wall_time - before_idle.wall_time)
    idle_cpu = max(0.0, after_idle.process_cpu_time - before_idle.process_cpu_time)
    workload_wall = max(0.0, after_workload.wall_time - before_workload.wall_time)
    workload_cpu = max(
        0.0, after_workload.process_cpu_time - before_workload.process_cpu_time
    )
    cpu_per_update = workload_cpu / updates
    return ClientBenchmarkResult(
        updates=updates,
        parser_frames=parser.frame_count,
        bytes_processed=packet_size * (updates + 1),
        idle_wall_seconds=idle_wall,
        idle_cpu_seconds=idle_cpu,
        idle_cpu_percent=(idle_cpu / idle_wall * 100.0) if idle_wall else 0.0,
        workload_wall_seconds=workload_wall,
        workload_cpu_seconds=workload_cpu,
        updates_per_second=(updates / workload_wall) if workload_wall else 0.0,
        estimated_cpu_percent_at_30hz=cpu_per_update * 30.0 * 100.0,
        resident_memory_before=before_idle.resident_memory_bytes,
        resident_memory_after=after_workload.resident_memory_bytes,
    )


def _packet(value: int) -> bytes:
    # Alternate a real state change without accidentally generating the four
    # byte DCS-BIOS synchronization marker inside the synthetic payload.
    payload = (value & 1).to_bytes(2, "little")
    return (
        SYNC
        + (0x1000).to_bytes(2, "little")
        + len(payload).to_bytes(2, "little")
        + payload
    )


def _safe_cruise_state() -> AircraftState:
    def value(item: T) -> TelemetryValue[T]:
        return TelemetryValue(item, True, 0.0, "benchmark")

    return AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        indicated_airspeed=value(350.0),
        gear_position=value(GearState.UP),
        canopy_state=value(CanopyState.CLOSED),
        master_caution=value(False),
        parking_brake=value(False),
        ejection_seat_armed=value(True),
        weight_on_wheels=value(False),
        engine_rpm_left=value(90.0),
        engine_rpm_right=value(90.0),
    )
