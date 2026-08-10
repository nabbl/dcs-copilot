"""Cloud development server entry point."""

from __future__ import annotations

import uvicorn

from .config import CloudSettings


def main() -> None:
    settings = CloudSettings.from_env()
    uvicorn.run(
        "dcs_copilot_cloud.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        ws_max_size=2 * 1024 * 1024,
        ws_max_queue=16,
        ws_per_message_deflate=False,
    )
