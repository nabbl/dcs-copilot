"""CLI adapter for the combined thin-client runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dcs_copilot.config import Settings
from dcs_copilot.desktop.auth import AuthError, StoredAuthSession
from dcs_copilot.desktop.config_store import DesktopConfig
from dcs_copilot.runtime import run_client_runtime


def run_client(
    settings: Settings,
    *,
    stdin_ptt: bool,
    coach_recording_path: Path | None = None,
) -> int:
    provider = None
    desktop = DesktopConfig.load()
    if (
        desktop.cloud_url == settings.cloud_url
        and desktop.device_id == settings.device_id
    ):
        auth = StoredAuthSession(settings.cloud_url, settings.device_id)

        async def refresh_access_token() -> str:
            try:
                return await asyncio.to_thread(auth.refresh)
            except AuthError as exc:
                raise RuntimeError(f"authentication refresh failed: {exc}") from exc

        provider = refresh_access_token
    try:
        return asyncio.run(
            run_client_runtime(
                settings,
                stdin_ptt=stdin_ptt,
                access_token_provider=provider,
                coach_recording_path=coach_recording_path,
            )
        )
    except KeyboardInterrupt:
        return 130
