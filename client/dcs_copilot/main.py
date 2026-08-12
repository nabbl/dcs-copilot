"""DCS Copilot command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .cli.run import run_client
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
    raise AssertionError(f"unhandled command: {args.command}")
