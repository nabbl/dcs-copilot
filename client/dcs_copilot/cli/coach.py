"""Thin developer handoff to the cloud-owned deterministic Coach replay CLI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def run_coach_replay(path: Path, *, exercise: str) -> int:
    executable = shutil.which("mara-coach")
    if executable is None:
        print(
            "Coach replay requires the cloud developer package; "
            "install the workspace and retry."
        )
        return 2
    completed = subprocess.run(
        [executable, "replay", str(path), "--exercise", exercise],
        check=False,
    )
    return completed.returncode
