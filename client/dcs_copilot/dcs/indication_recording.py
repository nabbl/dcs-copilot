"""Validation and replay for local raw indication discovery recordings."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .indications import MAX_ASSEMBLED_BYTES, MAX_INDICATORS, RawIndicatorState


MAX_RECORDING_BYTES = 256 * 1024 * 1024
MAX_EVENT_LINE_BYTES = MAX_ASSEMBLED_BYTES + 64 * 1024


class IndicationRecordingError(ValueError):
    """Raised when a recording cannot be trusted as a replay fixture."""


@dataclass(frozen=True, slots=True)
class IndicationRecording:
    path: Path
    metadata: dict[str, object]
    states: tuple[RawIndicatorState, ...]
    out_of_order_events: int
    duplicate_sequences: int

    def replay(self) -> Iterator[RawIndicatorState]:
        """Yield stored observations in file order without adding timing."""

        yield from self.states


def load_indication_recording(path: Path) -> IndicationRecording:
    """Load a recording directory and strictly validate its raw schema."""

    recording_path = path.expanduser().resolve()
    if recording_path.is_file() and recording_path.name == "events.jsonl":
        recording_path = recording_path.parent
    metadata_path = recording_path / "metadata.json"
    events_path = recording_path / "events.jsonl"
    metadata = _load_metadata(metadata_path)
    configured_ids = _configured_ids(metadata)
    states, out_of_order, duplicates = _load_events(events_path, configured_ids)
    expected_count = metadata.get("event_count")
    if expected_count is not None:
        if not isinstance(expected_count, int) or isinstance(expected_count, bool):
            raise IndicationRecordingError("metadata event_count must be an integer")
        if expected_count != len(states):
            raise IndicationRecordingError(
                f"metadata event_count is {expected_count}, "
                f"but {len(states)} events exist"
            )
    return IndicationRecording(
        path=recording_path,
        metadata=metadata,
        states=states,
        out_of_order_events=out_of_order,
        duplicate_sequences=duplicates,
    )


def _load_metadata(path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IndicationRecordingError(f"cannot read recording metadata: {exc}") from exc
    if size > 1024 * 1024:
        raise IndicationRecordingError("recording metadata exceeds 1 MiB")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndicationRecordingError(f"invalid recording metadata: {exc}") from exc
    if not isinstance(value, dict):
        raise IndicationRecordingError(
            "recording metadata must be a JSON object"
        )
    if value.get("format_version") != 1:
        raise IndicationRecordingError("unsupported recording format_version")
    scenario = value.get("scenario")
    if not isinstance(scenario, str) or not scenario:
        raise IndicationRecordingError("metadata scenario must be a non-empty string")
    _parse_timestamp(value.get("start_time"), "metadata start_time")
    if "end_time" in value:
        _parse_timestamp(value["end_time"], "metadata end_time")
    poll_hz = value.get("poll_hz")
    if (
        not isinstance(poll_hz, (int, float))
        or isinstance(poll_hz, bool)
        or not math.isfinite(float(poll_hz))
        or not 0.1 <= float(poll_hz) <= 10.0
    ):
        raise IndicationRecordingError("metadata poll_hz must be between 0.1 and 10")
    return value


def _configured_ids(metadata: dict[str, object]) -> frozenset[int]:
    values = metadata.get("indicator_ids")
    if not isinstance(values, list) or not values:
        raise IndicationRecordingError("metadata indicator_ids must be a non-empty list")
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < MAX_INDICATORS
        for value in values
    ):
        raise IndicationRecordingError("metadata contains an invalid indicator ID")
    if len(values) != len(set(values)):
        raise IndicationRecordingError(
            "metadata contains duplicate indicator IDs"
        )
    return frozenset(values)


def _load_events(
    path: Path,
    configured_ids: frozenset[int],
) -> tuple[tuple[RawIndicatorState, ...], int, int]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise IndicationRecordingError(f"cannot read recording events: {exc}") from exc
    if size > MAX_RECORDING_BYTES:
        raise IndicationRecordingError("recording exceeds the 256 MiB safety limit")

    states: list[RawIndicatorState] = []
    seen_sequences: set[int] = set()
    previous_sequence: int | None = None
    out_of_order = 0
    duplicates = 0
    try:
        with path.open("rb") as source:
            line_number = 0
            while True:
                line = source.readline(MAX_EVENT_LINE_BYTES + 1)
                if not line:
                    break
                line_number += 1
                if len(line) > MAX_EVENT_LINE_BYTES:
                    raise IndicationRecordingError(
                        f"event line {line_number} exceeds the size limit"
                    )
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise IndicationRecordingError(
                        f"event line {line_number} is invalid JSON: {exc}"
                    ) from exc
                state = _event_state(event, line_number, configured_ids)
                if state.sequence in seen_sequences:
                    duplicates += 1
                seen_sequences.add(state.sequence)
                if previous_sequence is not None and state.sequence < previous_sequence:
                    out_of_order += 1
                previous_sequence = state.sequence
                states.append(state)
    except OSError as exc:
        raise IndicationRecordingError(f"cannot read recording events: {exc}") from exc
    return tuple(states), out_of_order, duplicates


def _event_state(
    event: object,
    line_number: int,
    configured_ids: frozenset[int],
) -> RawIndicatorState:
    if not isinstance(event, dict):
        raise IndicationRecordingError(f"event line {line_number} must be an object")
    recorded_at = _parse_timestamp(
        event.get("recorded_at"), f"event line {line_number} recorded_at"
    )
    observed_at = _finite_number(
        event.get("observed_at_unix"),
        f"event line {line_number} observed_at_unix",
    )
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise IndicationRecordingError(
            f"event line {line_number} sequence must be a non-negative integer"
        )
    indicator_id = event.get("indicator_id")
    if (
        not isinstance(indicator_id, int)
        or isinstance(indicator_id, bool)
        or indicator_id not in configured_ids
    ):
        raise IndicationRecordingError(
            f"event line {line_number} indicator_id was not configured"
        )
    raw = event.get("raw")
    error = event.get("error")
    if not isinstance(raw, str):
        raise IndicationRecordingError(f"event line {line_number} raw must be a string")
    if error is not None and not isinstance(error, str):
        raise IndicationRecordingError(
            f"event line {line_number} error must be a string or null"
        )
    if error is not None and raw:
        raise IndicationRecordingError(
            f"event line {line_number} cannot contain both raw output and an error"
        )
    if len(raw.encode("utf-8")) > MAX_ASSEMBLED_BYTES:
        raise IndicationRecordingError(
            f"event line {line_number} raw output exceeds the size limit"
        )
    return RawIndicatorState(
        indicator_id=indicator_id,
        raw=raw,
        observed_at=observed_at,
        received_at=recorded_at.timestamp(),
        sequence=sequence,
        error=error,
    )


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise IndicationRecordingError(f"{label} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IndicationRecordingError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IndicationRecordingError(f"{label} must include a timezone")
    return parsed


def _finite_number(value: object, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise IndicationRecordingError(f"{label} must be a finite number")
    return float(value)
