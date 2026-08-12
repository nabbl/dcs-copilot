from __future__ import annotations

from dcs_copilot.main import build_parser


def test_cli_exposes_thin_client_commands() -> None:
    parser = build_parser()
    status = parser.parse_args(["status", "--wait", "0"])
    watch = parser.parse_args(
        ["watch", "--module", "FA-18C_hornet", "--control", "GEAR_LEVER"]
    )
    run = parser.parse_args(["run", "--stdin-ptt"])
    setup = parser.parse_args(["setup-dcs", "/tmp/DCS"])
    assert status.command == "status"
    assert status.wait == 0
    assert watch.command == "watch"
    assert watch.control == ["GEAR_LEVER"]
    assert run.command == "run"
    assert run.stdin_ptt is True
    assert setup.command == "setup-dcs"
