"""DCS Copilot command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli.benchmark import run_benchmark
from .cli.checklist import run_checklist_explain, run_checklist_status
from .cli.replay import run_replay
from .cli.run import run_client
from .cli.rules import run_carrier_launch_check, run_rule_explain, run_rules
from .cli.status import run_status
from .cli.watch import run_watch
from .config import Settings
from .desktop.config_store import DesktopConfig, discover_dcs_folders
from .desktop.dcs_setup import DcsSetupError, install_dcs_bios
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

    rules = subparsers.add_parser("rules", help="show deterministic rule diagnostics")
    rules.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )
    rules.add_argument(
        "--active",
        action="store_true",
        help="show only active deterministic rules",
    )

    rule = subparsers.add_parser("rule", help="inspect one deterministic rule")
    rule_subparsers = rule.add_subparsers(dest="rule_command", required=True)
    explain = rule_subparsers.add_parser("explain", help="explain one rule")
    explain.add_argument("rule_id", help="rule identifier to explain")
    explain.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )

    check = subparsers.add_parser("check", help="run deterministic configuration checks")
    check_subparsers = check.add_subparsers(dest="check_name", required=True)
    carrier_launch = check_subparsers.add_parser(
        "carrier-launch", help="check F/A-18C carrier launch configuration"
    )
    carrier_launch.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )

    checklist = subparsers.add_parser("checklist", help="inspect deterministic checklists")
    checklist_subparsers = checklist.add_subparsers(
        dest="checklist_command", required=True
    )
    checklist_status = checklist_subparsers.add_parser(
        "status", help="show checklist status"
    )
    checklist_status.add_argument("stage", nargs="?", help="checklist stage")
    checklist_status.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )
    checklist_explain = checklist_subparsers.add_parser(
        "explain", help="explain one checklist item"
    )
    checklist_explain.add_argument("item_id", help="checklist item id")
    checklist_explain.add_argument("--stage", help="checklist stage")
    checklist_explain.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to listen for DCS-BIOS frames (default: 2)",
    )

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
    setup_dcs = subparsers.add_parser(
        "setup-dcs", help="install the pinned DCS-BIOS release and configure Export.lua"
    )
    setup_dcs.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="DCS Saved Games folder; auto-detected when omitted",
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
    if args.command == "rules":
        return run_rules(settings, max(0.0, args.wait), active_only=args.active)
    if args.command == "rule":
        if args.rule_command == "explain":
            return run_rule_explain(settings, max(0.0, args.wait), args.rule_id)
        raise AssertionError(f"unhandled rule command: {args.rule_command}")
    if args.command == "check":
        if args.check_name == "carrier-launch":
            return run_carrier_launch_check(settings, max(0.0, args.wait))
        raise AssertionError(f"unhandled check: {args.check_name}")
    if args.command == "checklist":
        if args.checklist_command == "status":
            return run_checklist_status(settings, max(0.0, args.wait), args.stage)
        if args.checklist_command == "explain":
            return run_checklist_explain(
                settings,
                max(0.0, args.wait),
                args.item_id,
                args.stage,
            )
        raise AssertionError(f"unhandled checklist command: {args.checklist_command}")
    if args.command == "benchmark":
        return run_benchmark(
            updates=args.updates,
            idle_seconds=args.idle_seconds,
        )
    if args.command == "setup-dcs":
        configured = DesktopConfig.load()
        paths = [args.path] if args.path is not None else discover_dcs_folders()
        if not paths and configured.dcs_path is not None:
            paths = [configured.dcs_path]
        if not paths:
            print(
                "No DCS Saved Games folder was found; complete setup in the desktop app."
            )
            return 0
        try:
            for path in paths:
                result = install_dcs_bios(path)
                print(f"DCS-BIOS {result.version} ready in {result.dcs_path}")
        except DcsSetupError as exc:
            print(f"DCS setup failed: {exc}")
            return 1
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
