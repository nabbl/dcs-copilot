"""Raw F/A-18C indication discovery commands."""

from __future__ import annotations

import difflib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from dcs_copilot.dcs.indications import (
    MAX_INDICATORS,
    MAX_RANGE_SIZE,
    DcsIndicationReader,
    RawIndicatorState,
)
from dcs_copilot.dcs.fa18c_experiments import (
    EXPERIMENT_BY_SCENARIO,
    EXPERIMENTS,
)
from dcs_copilot.dcs.indication_recording import (
    IndicationRecordingError,
    load_indication_recording,
)
from dcs_copilot.desktop.dcs_setup import DCS_BIOS_VERSION


_SCENARIO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def run_indication_scan(
    *,
    first_id: int,
    last_id: int,
    timeout: float,
    control_port: int,
    reader: DcsIndicationReader | None = None,
) -> int:
    _validate_arguments(first_id, last_id)
    source = reader or DcsIndicationReader(control_port=control_port)
    states = source.scan(first_id, last_id, timeout=timeout)
    by_id = {state.indicator_id: state for state in states}
    for indicator_id in range(first_id, last_id + 1):
        state = by_id.get(indicator_id)
        print(f"Indicator {indicator_id}")
        print("-" * 40)
        if state is None:
            print("<NO RESPONSE>")
        elif state.error is not None:
            print(f"<ERROR: {state.error}>")
        else:
            print(state.raw)
        print()
    if len(states) != last_id - first_id + 1:
        print(
            "Indication probe did not answer for every ID. Start DCS and run "
            "`mara indications install` first."
        )
        return 2
    return 0


def run_indication_watch(
    *,
    first_id: int,
    last_id: int,
    poll_hz: float,
    diff: bool,
    control_port: int,
    reader: DcsIndicationReader | None = None,
) -> int:
    _validate_arguments(first_id, last_id, poll_hz)
    source = reader or DcsIndicationReader(control_port=control_port)
    previous: dict[int, str] = {}
    print(
        f"Watching indicators {first_id}-{last_id} at up to {poll_hz:g} Hz; "
        "press Ctrl-C to stop.",
        flush=True,
    )
    try:
        for state in source.watch(first_id, last_id, poll_hz=poll_hz):
            if diff:
                _print_diff(state, previous.get(state.indicator_id, ""))
            else:
                _print_state(state)
            previous[state.indicator_id] = state.raw
    except KeyboardInterrupt:
        return 130
    return 0


def run_indication_record(
    scenario: str,
    *,
    first_id: int,
    last_id: int,
    poll_hz: float,
    control_port: int,
    output_root: Path,
    aircraft: str | None,
    dcs_version: str | None,
    reader: DcsIndicationReader | None = None,
) -> int:
    _validate_arguments(first_id, last_id, poll_hz)
    if not _SCENARIO.fullmatch(scenario):
        print(
            "Scenario names must start with a letter or digit and contain only "
            "letters, digits, dot, underscore, or hyphen."
        )
        return 2
    recording = output_root.expanduser().resolve() / scenario
    try:
        recording.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"Recording already exists: {recording}")
        return 2

    started = datetime.now(UTC)
    metadata: dict[str, object] = {
        "format_version": 1,
        "scenario": scenario,
        "aircraft": aircraft,
        "dcs_version": dcs_version,
        "dcs_bios_version": DCS_BIOS_VERSION,
        "start_time": started.isoformat(),
        "indicator_ids": list(range(first_id, last_id + 1)),
        "poll_hz": poll_hz,
        "source": "DCS list_indication() via loopback probe",
    }
    experiment = EXPERIMENT_BY_SCENARIO.get(scenario)
    if experiment is not None:
        metadata["experiment"] = {
            "group": experiment.group,
            "action": experiment.action,
        }
    metadata_path = recording / "metadata.json"
    events_path = recording / "events.jsonl"
    _write_metadata(metadata_path, metadata)
    source = reader or DcsIndicationReader(control_port=control_port)
    event_count = 0
    exit_code = 0
    print(f"Recording raw indication changes to {recording}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    try:
        with events_path.open("x", encoding="utf-8", newline="\n") as events:
            for state in source.watch(first_id, last_id, poll_hz=poll_hz):
                event = {
                    "recorded_at": datetime.fromtimestamp(
                        state.received_at, UTC
                    ).isoformat(),
                    "observed_at_unix": state.observed_at,
                    "sequence": state.sequence,
                    "indicator_id": state.indicator_id,
                    "raw": state.raw,
                    "error": state.error,
                }
                events.write(json.dumps(event, ensure_ascii=False) + "\n")
                events.flush()
                event_count += 1
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        metadata["end_time"] = datetime.now(UTC).isoformat()
        metadata["event_count"] = event_count
        _write_metadata(metadata_path, metadata)
    print(f"Recorded {event_count} changed indicator states.")
    return exit_code


def run_indication_validate(path: Path) -> int:
    try:
        recording = load_indication_recording(path)
    except IndicationRecordingError as exc:
        print(f"INVALID: {exc}")
        return 2
    print(f"VALID: {recording.path}")
    print(f"Scenario: {recording.metadata['scenario']}")
    print(f"Events: {len(recording.states)}")
    print(f"Out-of-order events: {recording.out_of_order_events}")
    print(f"Duplicate sequences: {recording.duplicate_sequences}")
    return 0


def run_indication_replay(path: Path, *, diff: bool) -> int:
    try:
        recording = load_indication_recording(path)
    except IndicationRecordingError as exc:
        print(f"Cannot replay recording: {exc}")
        return 2
    previous: dict[int, str] = {}
    print(
        f"Replaying {recording.metadata['scenario']} "
        f"({len(recording.states)} events)"
    )
    for state in recording.replay():
        if diff:
            _print_diff(state, previous.get(state.indicator_id, ""))
        else:
            _print_state(state)
        previous[state.indicator_id] = state.raw
    return 0


def run_indication_experiments(output_root: Path) -> int:
    root = output_root.expanduser().resolve()
    counts = {"RECORDED": 0, "PENDING": 0, "INVALID": 0}
    current_group: str | None = None
    for experiment in EXPERIMENTS:
        if experiment.group != current_group:
            current_group = experiment.group
            print(f"\n{current_group}")
        path = root / experiment.scenario
        if not path.exists():
            status = "PENDING"
            detail = experiment.action
        else:
            try:
                recording = load_indication_recording(path)
            except IndicationRecordingError as exc:
                status = "INVALID"
                detail = str(exc)
            else:
                status = "RECORDED"
                detail = f"{len(recording.states)} events"
        counts[status] += 1
        print(f"  {status:8} {experiment.scenario:27} {detail}")
    print(
        "\nSummary: "
        f"{counts['RECORDED']} recorded, {counts['PENDING']} pending, "
        f"{counts['INVALID']} invalid"
    )
    return 2 if counts["INVALID"] else 0


def _print_state(state: RawIndicatorState) -> None:
    timestamp = _local_time(state.received_at)
    print(f"[{timestamp}]\n")
    print(f"INDICATOR {state.indicator_id}")
    print("-" * 40)
    print(f"<ERROR: {state.error}>" if state.error is not None else state.raw)
    print(flush=True)


def _print_diff(state: RawIndicatorState, old: str) -> None:
    timestamp = _local_time(state.received_at)
    print(f"[{timestamp}]\n")
    print(f"INDICATOR {state.indicator_id} CHANGED\n")
    if state.error is not None:
        print(f"+ <ERROR: {state.error}>")
    else:
        changes = difflib.ndiff(old.splitlines(), state.raw.splitlines())
        for line in changes:
            if line.startswith("- "):
                print(f"- {line[2:]}")
            elif line.startswith("+ "):
                print(f"+ {line[2:]}")
    print(flush=True)


def _local_time(timestamp: float) -> str:
    local = datetime.fromtimestamp(timestamp, UTC).astimezone()
    return local.strftime("%H:%M:%S.%f")[:-3]


def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _validate_arguments(
    first_id: int,
    last_id: int,
    poll_hz: float | None = None,
) -> None:
    if not 0 <= first_id < MAX_INDICATORS:
        raise ValueError(
            f"first indicator ID must be between 0 and {MAX_INDICATORS - 1}"
        )
    if not first_id <= last_id < MAX_INDICATORS:
        raise ValueError(
            f"last indicator ID must be between first ID and {MAX_INDICATORS - 1}"
        )
    if last_id - first_id + 1 > MAX_RANGE_SIZE:
        raise ValueError(
            f"indicator range cannot contain more than {MAX_RANGE_SIZE} IDs"
        )
    if poll_hz is not None and not 0.1 <= poll_hz <= 10.0:
        raise ValueError("poll rate must be between 0.1 and 10 Hz")
