"""Conservative deterministic flight-phase inference with hysteresis."""

from __future__ import annotations

from dataclasses import dataclass, field

from .history import StateHistory
from .models import AircraftState, FlightPhase, GearState


@dataclass(frozen=True, slots=True)
class PhaseDetectorConfig:
    default_dwell_seconds: float = 1.5
    phase_dwell_seconds: dict[FlightPhase, float] = field(
        default_factory=lambda: {
            FlightPhase.REFUELING: 0.75,
            FlightPhase.LANDING: 0.75,
            FlightPhase.POST_LANDING: 0.75,
            FlightPhase.UNKNOWN: 0.0,
        }
    )
    taxi_min_speed: float = 3.0
    takeoff_roll_speed: float = 80.0
    airborne_min_speed: float = 90.0
    approach_max_speed: float = 250.0
    landing_max_speed: float = 160.0
    climb_rate_fpm: float = 300.0
    takeoff_airborne_hold_seconds: float = 20.0


class FlightPhaseDetector:
    def __init__(self, config: PhaseDetectorConfig | None = None) -> None:
        self.config = config or PhaseDetectorConfig()
        self.current = FlightPhase.UNKNOWN
        self._candidate = FlightPhase.UNKNOWN
        self._candidate_since: float | None = None
        self._phase_since: float | None = None

    def update(
        self, state: AircraftState, history: StateHistory, *, now: float
    ) -> FlightPhase:
        inferred = self._infer(state, history, now=now)
        if inferred == self.current:
            self._candidate = inferred
            self._candidate_since = None
            return self.current
        if inferred != self._candidate:
            self._candidate = inferred
            self._candidate_since = now
        dwell = self.config.phase_dwell_seconds.get(
            inferred, self.config.default_dwell_seconds
        )
        if self._candidate_since is not None and now - self._candidate_since >= dwell:
            self.current = inferred
            self._phase_since = now
            self._candidate_since = None
        return self.current

    def reset(self) -> None:
        self.current = FlightPhase.UNKNOWN
        self._candidate = FlightPhase.UNKNOWN
        self._candidate_since = None
        self._phase_since = None

    def _infer(
        self, state: AircraftState, history: StateHistory, *, now: float
    ) -> FlightPhase:
        if not state.connected or not state.weight_on_wheels.usable:
            return FlightPhase.UNKNOWN
        wow = bool(state.weight_on_wheels.value)
        speed = (
            float(state.indicated_airspeed.value)
            if state.indicated_airspeed.usable
            and state.indicated_airspeed.value is not None
            else None
        )
        engines = self._engine_state(state)

        if wow:
            if (
                speed is not None
                and speed >= self.config.takeoff_roll_speed
                and engines == "running"
            ):
                return FlightPhase.TAKEOFF
            if history.changed_within(
                "weight_on_wheels",
                old_value=False,
                new_value=True,
                seconds=20.0,
                now=now,
            ):
                return FlightPhase.POST_LANDING
            if (
                self.current is FlightPhase.POST_LANDING
                and engines != "off"
                and speed is not None
            ):
                return FlightPhase.POST_LANDING
            if (
                speed is not None
                and speed >= self.config.taxi_min_speed
                and engines == "running"
            ):
                return FlightPhase.TAXI
            if engines == "off":
                return FlightPhase.COLD_DARK
            if (
                engines in {"starting", "running"}
                and speed is not None
                and speed < self.config.taxi_min_speed
            ):
                return FlightPhase.STARTUP
            return FlightPhase.UNKNOWN

        if speed is None or speed < self.config.airborne_min_speed:
            return FlightPhase.UNKNOWN
        fuel_rate_ppm = history.rate("fuel_quantity", seconds=10.0, now=now)
        if (
            state.refueling_probe.usable
            and state.refueling_probe.value
            and fuel_rate_ppm is not None
            and fuel_rate_ppm * 60 >= 50
        ):
            return FlightPhase.REFUELING
        gear = state.gear_position.value if state.gear_position.usable else None
        if history.changed_within(
            "weight_on_wheels",
            old_value=True,
            new_value=False,
            seconds=self.config.takeoff_airborne_hold_seconds,
            now=now,
        ):
            return FlightPhase.TAKEOFF
        if (
            self.current is FlightPhase.TAKEOFF
            and self._phase_since is not None
            and now - self._phase_since < self.config.takeoff_airborne_hold_seconds
        ):
            return FlightPhase.TAKEOFF
        altitude_rate_fps = history.rate("altitude_msl", seconds=10.0, now=now)
        if (
            gear is GearState.DOWN
            and speed <= self.config.landing_max_speed
            and altitude_rate_fps is not None
            and altitude_rate_fps * 60 <= -100
        ):
            return FlightPhase.LANDING
        if (
            gear in {GearState.DOWN, GearState.TRANSIT}
            and speed <= self.config.approach_max_speed
        ):
            return FlightPhase.APPROACH
        if (
            altitude_rate_fps is not None
            and altitude_rate_fps * 60 >= self.config.climb_rate_fpm
        ):
            return FlightPhase.CLIMB
        if gear is GearState.UP:
            return FlightPhase.CRUISE
        return FlightPhase.UNKNOWN

    @staticmethod
    def _engine_state(state: AircraftState) -> str | None:
        if not state.engine_rpm_left.usable or not state.engine_rpm_right.usable:
            return None
        assert state.engine_rpm_left.value is not None
        assert state.engine_rpm_right.value is not None
        rpms = (float(state.engine_rpm_left.value), float(state.engine_rpm_right.value))
        if max(rpms) <= 5:
            return "off"
        if min(rpms) >= 60:
            return "running"
        return "starting"
