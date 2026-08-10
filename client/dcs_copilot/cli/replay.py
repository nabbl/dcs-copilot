"""CLI for deterministic normalized-state replay."""

from __future__ import annotations

from pathlib import Path

from dcs_copilot.replay.player import ReplayPlayer


def run_replay(path: Path) -> int:
    player = ReplayPlayer()
    try:
        result = player.run(path)
    except (OSError, ValueError) as exc:
        print(f"Replay failed: {exc}")
        return 2
    for transition in result.transitions:
        print(
            f"{transition.timestamp:8.2f}s {transition.type}: "
            f"{transition.issue.rule_id} [{transition.issue.severity}] "
            f"{transition.issue.message}"
        )
    print(
        f"Replay complete: {result.frame_count} frames, "
        f"{result.active_issue_count} active issues, phase {result.final_phase}"
    )
    return 0
