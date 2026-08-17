"""Developer CLI for deterministic normalized Coach replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .exercises.base import ExerciseId
from .replay import CoachReplayError, replay_exercise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mara-coach")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="replay normalized Coach JSONL")
    replay.add_argument("path", type=Path)
    replay.add_argument(
        "--exercise",
        choices=[item.value for item in ExerciseId],
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "replay":
        raise AssertionError(f"unknown command: {args.command}")
    try:
        debrief = replay_exercise(args.path, args.exercise)
    except CoachReplayError as exc:
        print(f"Coach replay failed: {exc}")
        return 2
    print(json.dumps(debrief, indent=2, sort_keys=True))
    return 0
