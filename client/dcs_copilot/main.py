"""DCS Copilot command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli.benchmark import run_benchmark
from .cli.replay import run_replay
from .cli.run import run_client
from .cli.status import run_status
from .cli.watch import run_watch
from .config import Settings
from .logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dcs-copilot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="show a bounded diagnostics snapshot")
    status.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )

    run = subparsers.add_parser(
        "run", help="run DCS monitoring, cloud session, and PTT audio"
    )
    run.add_argument(
        "--stdin-ptt",
        action="store_true",
        help="development only: use Enter to toggle PTT instead of a Windows hotkey",
    )

    watch = subparsers.add_parser("watch", help="show normalized state changes")
    watch.add_argument(
        "--raw",
        action="store_true",
        help="show DCS-BIOS controls instead of normalized fields",
    )
    watch.add_argument("--module", help="show only one DCS-BIOS module")
    watch.add_argument(
        "--control",
        action="append",
        default=[],
        help="show one identifier (repeatable)",
    )

    replay = subparsers.add_parser(
        "replay", help="run normalized JSONL through phase detection and rules"
    )
    replay.add_argument("recording", type=Path, help="normalized JSONL recording")

    benchmark = subparsers.add_parser(
        "benchmark", help="measure the dependency-free client workload"
    )
    benchmark.add_argument(
        "--updates",
        type=int,
        default=30_000,
        help="synthetic 30 Hz updates to process (default: 30000)",
    )
    benchmark.add_argument(
        "--idle-seconds",
        type=float,
        default=1.0,
        help="idle CPU sampling interval (default: 1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if args.command == "status":
        return run_status(settings, max(0.0, args.wait))
    if args.command == "run":
        return run_client(settings, stdin_ptt=args.stdin_ptt)
    if args.command == "watch":
        return run_watch(
            settings,
            raw=args.raw,
            module=args.module,
            controls=args.control,
        )
    if args.command == "replay":
        return run_replay(args.recording)
    if args.command == "benchmark":
        return run_benchmark(
            updates=args.updates,
            idle_seconds=args.idle_seconds,
        )
    raise AssertionError(f"unhandled command: {args.command}")
