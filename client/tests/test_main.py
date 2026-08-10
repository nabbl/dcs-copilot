from __future__ import annotations

from dcs_copilot.main import build_parser


def test_cli_exposes_thin_client_commands() -> None:
    parser = build_parser()
    status = parser.parse_args(["status", "--wait", "0"])
    watch = parser.parse_args(
        ["watch", "--module", "FA-18C_hornet", "--control", "GEAR_LEVER"]
    )
    benchmark = parser.parse_args(
        ["benchmark", "--updates", "300", "--idle-seconds", "0"]
    )
    run = parser.parse_args(["run", "--stdin-ptt"])
    assert status.command == "status"
    assert status.wait == 0
    assert watch.command == "watch"
    assert watch.control == ["GEAR_LEVER"]
    assert watch.raw is False
    assert benchmark.command == "benchmark"
    assert benchmark.updates == 300
    assert benchmark.idle_seconds == 0
    assert run.command == "run"
    assert run.stdin_ptt is True
