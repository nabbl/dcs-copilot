"""Normalized exercise recording and deterministic offline replay."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TextIO

from dcs_copilot_protocol import CoachTelemetry, ControlMessage, ProtocolError

from .coordinator import CoachCoordinator
from .exercises.base import ExerciseId
from .ingress import CoachTelemetryIngress

MAX_RECORDING_BYTES = 128 * 1024 * 1024
MAX_LINE_BYTES = 256 * 1024


class CoachReplayError(ValueError):
    pass


class CoachRecordingWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._output: TextIO | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._output = self.path.open("w", encoding="utf-8", newline="\n")
        return self

    def write(self, timestamp: float, telemetry: CoachTelemetry) -> None:
        if self._output is None:
            raise CoachReplayError("recording writer is not open")
        if not math.isfinite(timestamp) or timestamp < 0:
            raise CoachReplayError(
                "Coach recording timestamp must be finite and nonnegative"
            )
        document = {
            "t": timestamp,
            "telemetry": telemetry.to_control().payload,
        }
        encoded = json.dumps(document, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_LINE_BYTES:
            raise CoachReplayError("Coach recording line exceeds 256 KiB")
        self._output.write(encoded + "\n")

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._output is not None:
            self._output.close()
            self._output = None


def read_recording(path: Path) -> Iterator[tuple[float, CoachTelemetry]]:
    if not path.is_file():
        raise CoachReplayError(f"Coach recording does not exist: {path}")
    if path.stat().st_size > MAX_RECORDING_BYTES:
        raise CoachReplayError("Coach recording exceeds 128 MiB")
    previous = float("-inf")
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw in enumerate(source, start=1):
            if len(raw.encode("utf-8")) > MAX_LINE_BYTES:
                raise CoachReplayError(f"line {line_number} exceeds 256 KiB")
            try:
                document = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CoachReplayError(f"line {line_number} is invalid JSON") from exc
            if not isinstance(document, dict) or set(document) != {"t", "telemetry"}:
                raise CoachReplayError(f"line {line_number} has an invalid shape")
            timestamp = document["t"]
            if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
                raise CoachReplayError(f"line {line_number} timestamp is invalid")
            timestamp = float(timestamp)
            if not math.isfinite(timestamp) or timestamp < 0:
                raise CoachReplayError(f"line {line_number} timestamp is invalid")
            if timestamp < previous:
                raise CoachReplayError("Coach recording timestamps are out of order")
            previous = timestamp
            telemetry = document["telemetry"]
            if not isinstance(telemetry, dict):
                raise CoachReplayError(f"line {line_number} telemetry is invalid")
            try:
                yield (
                    timestamp,
                    CoachTelemetry.from_control(
                        ControlMessage("coach.telemetry", telemetry)
                    ),
                )
            except ProtocolError as exc:
                raise CoachReplayError(
                    f"line {line_number} contains invalid Coach telemetry: {exc}"
                ) from exc


def replay_exercise(path: Path, exercise: ExerciseId | str) -> dict[str, Any]:
    frames = iter(read_recording(path))
    try:
        first_timestamp, first = next(frames)
    except StopIteration as exc:
        raise CoachReplayError("Coach recording is empty") from exc
    coordinator = CoachCoordinator()
    ingress = CoachTelemetryIngress(coordinator)
    ingress.accept(first, received_at=first_timestamp)
    coordinator.start(ExerciseId(exercise), now=first_timestamp)
    last_timestamp = first_timestamp
    for timestamp, telemetry in frames:
        ingress.accept(telemetry, received_at=timestamp)
        last_timestamp = timestamp
    coordinator.stop(now=last_timestamp)
    if coordinator.last_debrief is None:
        raise CoachReplayError("exercise did not produce a debrief")
    return coordinator.last_debrief
