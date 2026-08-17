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
    scan = parser.parse_args(
        ["indications", "scan", "--first-id", "2", "--last-id", "8"]
    )
    indication_watch = parser.parse_args(["indications", "watch", "--diff"])
    record = parser.parse_args(["indications", "record", "radar-lock-test"])
    install = parser.parse_args(["indications", "install", "/tmp/DCS"])
    experiments = parser.parse_args(["indications", "experiments"])
    validate = parser.parse_args(["indications", "validate", "/tmp/recording"])
    replay = parser.parse_args(
        ["indications", "replay", "/tmp/recording", "--diff"]
    )
    assert status.command == "status"
    assert status.wait == 0
    assert watch.command == "watch"
    assert watch.control == ["GEAR_LEVER"]
    assert run.command == "run"
    assert run.stdin_ptt is True
    assert setup.command == "setup-dcs"
    assert scan.indications_command == "scan"
    assert scan.first_id == 2
    assert scan.last_id == 8
    assert indication_watch.diff is True
    assert record.scenario == "radar-lock-test"
    assert install.path.as_posix() == "/tmp/DCS"
    assert experiments.indications_command == "experiments"
    assert validate.path.as_posix() == "/tmp/recording"
    assert replay.diff is True
