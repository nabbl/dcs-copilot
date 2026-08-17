from __future__ import annotations

import json
from pathlib import Path

import pytest

from dcs_copilot.dcs.indication_recording import (
    IndicationRecordingError,
    load_indication_recording,
)


def _write_recording(
    root: Path,
    events: list[dict[str, object]],
    *,
    event_count: int | None = None,
) -> Path:
    recording = root / "radar-lock-lost"
    recording.mkdir()
    metadata: dict[str, object] = {
        "format_version": 1,
        "scenario": "radar-lock-lost",
        "aircraft": "FA-18C_hornet",
        "dcs_version": "2.9-test",
        "dcs_bios_version": "0.11.5",
        "start_time": "2026-08-14T12:00:00+00:00",
        "end_time": "2026-08-14T12:00:05+00:00",
        "indicator_ids": [4, 5],
        "poll_hz": 10,
    }
    if event_count is not None:
        metadata["event_count"] = event_count
    (recording / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    (recording / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return recording


def _event(sequence: int, *, indicator_id: int = 4) -> dict[str, object]:
    return {
        "recorded_at": "2026-08-14T12:00:01+00:00",
        "observed_at_unix": 1786708801.0,
        "sequence": sequence,
        "indicator_id": indicator_id,
        "raw": "lock = false",
        "error": None,
    }


def test_loads_and_replays_valid_recording(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, [_event(10), _event(11)], event_count=2)

    recording = load_indication_recording(path)

    assert recording.metadata["scenario"] == "radar-lock-lost"
    assert [state.sequence for state in recording.replay()] == [10, 11]
    assert recording.out_of_order_events == 0
    assert recording.duplicate_sequences == 0


def test_preserves_out_of_order_and_duplicate_events_for_parser_tests(
    tmp_path: Path,
) -> None:
    path = _write_recording(tmp_path, [_event(11), _event(10), _event(10)])

    recording = load_indication_recording(path)

    assert [state.sequence for state in recording.replay()] == [11, 10, 10]
    assert recording.out_of_order_events == 1
    assert recording.duplicate_sequences == 1


def test_rejects_event_from_an_unconfigured_indicator(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, [_event(1, indicator_id=6)])

    with pytest.raises(IndicationRecordingError, match="was not configured"):
        load_indication_recording(path)


def test_rejects_event_count_mismatch(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, [_event(1)], event_count=2)

    with pytest.raises(IndicationRecordingError, match="event_count"):
        load_indication_recording(path)


def test_rejects_naive_timestamps(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, [_event(1)])
    metadata_path = path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["start_time"] = "2026-08-14T12:00:00"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(IndicationRecordingError, match="timezone"):
        load_indication_recording(path)
