"""CLI adapter for the combined thin-client runtime."""

from __future__ import annotations

import asyncio

from dcs_copilot.config import Settings
from dcs_copilot.runtime import run_client_runtime


def run_client(settings: Settings, *, stdin_ptt: bool) -> int:
    try:
        return asyncio.run(run_client_runtime(settings, stdin_ptt=stdin_ptt))
    except KeyboardInterrupt:
        return 130
