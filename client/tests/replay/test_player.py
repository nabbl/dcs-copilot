from __future__ import annotations

from pathlib import Path

import pytest
from dcs_copilot.replay.player import ReplayPlayer
from dcs_copilot.rules.base import RuleTransitionType
from dcs_copilot.state.models import FlightPhase

FIXTURES = Path(__file__).parents[1] / "fixtures" / "replay"


def test_taxi_fixture_drives_phase_rules_and_resolution() -> None:
    result = ReplayPlayer().run(FIXTURES / "taxi-mistakes.jsonl")
    activated = {
        item.issue.rule_id
        for item in result.transitions
        if item.type is RuleTransitionType.ACTIVATED
    }
    resolved = {
        item.issue.rule_id
        for item in result.transitions
        if item.type is RuleTransitionType.RESOLVED
    }
    assert activated == {
        "FA18_PARKING_BRAKE_TAXI",
        "FA18_EJECTION_SEAT_NOT_ARMED",
    }
    assert resolved == activated
    assert result.active_issue_count == 0
    assert result.event_count == 4
    assert result.final_phase is FlightPhase.TAXI


def test_airborne_fixture_triggers_and_resolves_three_rules() -> None:
    player = ReplayPlayer()
    result = player.run(FIXTURES / "airborne-alerts.jsonl")
    activated = {
        item.issue.rule_id
        for item in result.transitions
        if item.type is RuleTransitionType.ACTIVATED
    }
    resolved = {
        item.issue.rule_id
        for item in result.transitions
        if item.type is RuleTransitionType.RESOLVED
    }
    assert activated == {
        "FA18_MASTER_CAUTION",
        "FA18_GEAR_OVERSPEED",
        "FA18_CANOPY_OPEN_MOVING",
    }
    assert resolved == activated
    assert result.active_issue_count == 0
    assert result.event_count == 6
    assert result.final_phase is FlightPhase.TAKEOFF
    assert player.run(FIXTURES / "airborne-alerts.jsonl") == result


def test_replay_rejects_unknown_fields_and_time_travel(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text('{"timestamp":0,"fields":{"magic_radar":true}}\n')
    with pytest.raises(ValueError, match="unknown normalized fields"):
        ReplayPlayer().load(unknown)

    backwards = tmp_path / "backwards.jsonl"
    backwards.write_text('{"timestamp":2}\n{"timestamp":1}\n')
    with pytest.raises(ValueError, match="timestamps must be nondecreasing"):
        ReplayPlayer().load(backwards)
