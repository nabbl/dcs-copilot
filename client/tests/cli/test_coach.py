from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dcs_copilot.cli.coach import run_coach_replay


def test_replay_command_delegates_to_cloud_owned_cli(monkeypatch) -> None:
    invoked: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda _name: "/workspace/bin/mara-coach")

    def run(command, *, check):
        invoked.append(command)
        assert check is False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", run)

    result = run_coach_replay(Path("flight.jsonl"), exercise="CASE1_PATTERN")

    assert result == 0
    assert invoked == [
        [
            "/workspace/bin/mara-coach",
            "replay",
            "flight.jsonl",
            "--exercise",
            "CASE1_PATTERN",
        ]
    ]


def test_replay_command_fails_cleanly_without_cloud_package(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)

    assert run_coach_replay(Path("flight.jsonl"), exercise="CASE1_PATTERN") == 2
