from __future__ import annotations

import json
from pathlib import Path

from dcs_copilot.cli.indications import (
    run_indication_experiments,
    run_indication_record,
    run_indication_replay,
    run_indication_scan,
    run_indication_validate,
    run_indication_watch,
)
from dcs_copilot.dcs.indications import RawIndicatorState


def _state(indicator_id: int, raw: str, sequence: int = 1) -> RawIndicatorState:
    return RawIndicatorState(
        indicator_id=indicator_id,
        raw=raw,
        observed_at=1720000000.0 + sequence,
        received_at=1720000000.0 + sequence,
        sequence=sequence,
    )


class FakeReader:
    def __init__(self, states: list[RawIndicatorState]) -> None:
        self.states = states

    def scan(self, first_id: int, last_id: int, *, timeout: float):
        return tuple(self.states)

    def watch(self, first_id: int, last_id: int, *, poll_hz: float):
        yield from self.states


def test_scan_prints_raw_empty_and_missing_indicators(capsys) -> None:
    result = run_indication_scan(
        first_id=0,
        last_id=2,
        timeout=1,
        control_port=7779,
        reader=FakeReader([_state(0, "HUD"), _state(1, "")]),
    )

    output = capsys.readouterr().out
    assert result == 2
    assert "Indicator 0" in output
    assert "HUD" in output
    assert "Indicator 1" in output
    assert "Indicator 2\n" in output
    assert "<NO RESPONSE>" in output


def test_diff_watch_prints_only_changed_lines(capsys) -> None:
    result = run_indication_watch(
        first_id=4,
        last_id=4,
        poll_hz=5,
        diff=True,
        control_port=7779,
        reader=FakeReader(
            [
                _state(4, "mode = RWS\nrange = 40", 1),
                _state(4, "mode = RWS\nrange = 80", 2),
            ]
        ),
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "+ mode = RWS" in output
    assert "- range = 40" in output
    assert "+ range = 80" in output


def test_record_writes_metadata_and_replayable_jsonl(tmp_path: Path) -> None:
    result = run_indication_record(
        "radar-lock-test",
        first_id=4,
        last_id=5,
        poll_hz=10,
        control_port=7779,
        output_root=tmp_path,
        aircraft="FA-18C_hornet",
        dcs_version="2.9-test",
        reader=FakeReader([_state(4, "lock = true")]),
    )

    recording = tmp_path / "radar-lock-test"
    metadata = json.loads((recording / "metadata.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (recording / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result == 0
    assert metadata["aircraft"] == "FA-18C_hornet"
    assert metadata["indicator_ids"] == [4, 5]
    assert metadata["event_count"] == 1
    assert metadata["end_time"]
    assert events[0]["indicator_id"] == 4
    assert events[0]["raw"] == "lock = true"


def test_record_rejects_unsafe_scenario_name(tmp_path: Path) -> None:
    result = run_indication_record(
        "../outside",
        first_id=0,
        last_id=1,
        poll_hz=10,
        control_port=7779,
        output_root=tmp_path,
        aircraft=None,
        dcs_version=None,
        reader=FakeReader([]),
    )

    assert result == 2
    assert not (tmp_path.parent / "outside").exists()


def test_validate_and_replay_recording(tmp_path: Path, capsys) -> None:
    assert (
        run_indication_record(
            "radar-off",
            first_id=4,
            last_id=4,
            poll_hz=10,
            control_port=7779,
            output_root=tmp_path,
            aircraft="FA-18C_hornet",
            dcs_version="2.9-test",
            reader=FakeReader([_state(4, "radar = OFF")]),
        )
        == 0
    )
    capsys.readouterr()

    metadata = json.loads(
        (tmp_path / "radar-off" / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["experiment"]["group"] == "RADAR"

    assert run_indication_validate(tmp_path / "radar-off") == 0
    assert run_indication_replay(tmp_path / "radar-off", diff=True) == 0

    output = capsys.readouterr().out
    assert "VALID:" in output
    assert "Scenario: radar-off" in output
    assert "Replaying radar-off (1 events)" in output
    assert "+ radar = OFF" in output


def test_experiment_matrix_reports_recording_progress(tmp_path: Path, capsys) -> None:
    result = run_indication_experiments(tmp_path)

    output = capsys.readouterr().out
    assert result == 0
    assert "RADAR" in output
    assert "radar-off" in output
    assert "RWR" in output
    assert "rwr-missile-launch" in output
    assert "0 recorded, 36 pending, 0 invalid" in output
