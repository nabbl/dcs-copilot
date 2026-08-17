"""DCS Copilot command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli.indications import (
    run_indication_experiments,
    run_indication_record,
    run_indication_replay,
    run_indication_scan,
    run_indication_validate,
    run_indication_watch,
)
from .cli.run import run_client
from .cli.status import run_status
from .cli.watch import run_watch
from .config import Settings
from .desktop.config_store import DesktopConfig, discover_dcs_folders
from .desktop.dcs_setup import (
    DcsSetupError,
    install_dcs_bios,
    install_indication_probe,
)
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

    watch = subparsers.add_parser("watch", help="show decoded DCS-BIOS output changes")
    watch.add_argument("--module", help="show only one DCS-BIOS module")
    watch.add_argument(
        "--control",
        action="append",
        default=[],
        help="show one identifier (repeatable)",
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

    indications = subparsers.add_parser(
        "indications", help="discover raw DCS list_indication() output"
    )
    indication_commands = indications.add_subparsers(
        dest="indications_command", required=True
    )

    scan = indication_commands.add_parser(
        "scan", help="take one raw snapshot across an indicator ID range"
    )
    _add_indication_range(scan)
    scan.add_argument(
        "--timeout", type=float, default=2.0, help="response timeout in seconds"
    )

    indication_watch = indication_commands.add_parser(
        "watch", help="watch change-driven raw indication output"
    )
    _add_indication_range(indication_watch)
    indication_watch.add_argument(
        "--hz", type=float, default=10.0, help="maximum poll rate (0.1-10 Hz)"
    )
    indication_watch.add_argument(
        "--diff", action="store_true", help="print only changed raw lines"
    )

    record = indication_commands.add_parser(
        "record", help="record timestamped raw indication changes locally"
    )
    record.add_argument("scenario", help="short filesystem-safe scenario name")
    _add_indication_range(record)
    record.add_argument(
        "--hz", type=float, default=10.0, help="maximum poll rate (0.1-10 Hz)"
    )
    record.add_argument(
        "--output-root",
        type=Path,
        default=Path("diagnostics/indication-recordings"),
        help="recording parent directory",
    )
    record.add_argument("--aircraft", help="aircraft/module metadata, if known")
    record.add_argument("--dcs-version", help="DCS version metadata, if known")

    install = indication_commands.add_parser(
        "install", help="install the development-only loopback DCS probe"
    )
    install.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="DCS Saved Games folder; auto-detected when omitted",
    )

    experiments = indication_commands.add_parser(
        "experiments", help="show the controlled F/A-18C recording matrix"
    )
    experiments.add_argument(
        "--output-root",
        type=Path,
        default=Path("diagnostics/indication-recordings"),
        help="recording parent directory",
    )

    validate = indication_commands.add_parser(
        "validate", help="validate one raw indication recording"
    )
    validate.add_argument("path", type=Path)

    replay = indication_commands.add_parser(
        "replay", help="replay one validated raw indication recording"
    )
    replay.add_argument("path", type=Path)
    replay.add_argument(
        "--diff", action="store_true", help="print only changed raw lines"
    )
    return parser


def _add_indication_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--first-id", type=int, default=0)
    parser.add_argument("--last-id", type=int, default=30)


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
            module=args.module,
            controls=args.control,
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
    if args.command == "indications":
        if args.indications_command == "scan":
            try:
                return run_indication_scan(
                    first_id=args.first_id,
                    last_id=args.last_id,
                    timeout=max(0.0, args.timeout),
                    control_port=settings.indication_control_port,
                )
            except (OSError, ValueError) as exc:
                print(f"Indication scan failed: {exc}")
                return 2
        if args.indications_command == "watch":
            try:
                return run_indication_watch(
                    first_id=args.first_id,
                    last_id=args.last_id,
                    poll_hz=args.hz,
                    diff=args.diff,
                    control_port=settings.indication_control_port,
                )
            except (OSError, ValueError) as exc:
                print(f"Indication watch failed: {exc}")
                return 2
        if args.indications_command == "record":
            try:
                return run_indication_record(
                    args.scenario,
                    first_id=args.first_id,
                    last_id=args.last_id,
                    poll_hz=args.hz,
                    control_port=settings.indication_control_port,
                    output_root=args.output_root,
                    aircraft=args.aircraft,
                    dcs_version=args.dcs_version,
                )
            except (OSError, ValueError) as exc:
                print(f"Indication recording failed: {exc}")
                return 2
        if args.indications_command == "install":
            configured = DesktopConfig.load()
            paths = [args.path] if args.path is not None else discover_dcs_folders()
            if not paths and configured.dcs_path is not None:
                paths = [configured.dcs_path]
            if not paths:
                print("No DCS Saved Games folder was found; pass its path explicitly.")
                return 2
            try:
                for path in paths:
                    result = install_indication_probe(path)
                    print(f"MARA indication probe ready in {result.dcs_path}")
            except DcsSetupError as exc:
                print(f"Indication probe setup failed: {exc}")
                return 1
            return 0
        if args.indications_command == "experiments":
            return run_indication_experiments(args.output_root)
        if args.indications_command == "validate":
            return run_indication_validate(args.path)
        if args.indications_command == "replay":
            return run_indication_replay(args.path, diff=args.diff)
        raise AssertionError(
            f"unhandled indications command: {args.indications_command}"
        )
    raise AssertionError(f"unhandled command: {args.command}")
