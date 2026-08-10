"""Bounded authenticated cloud probe used by the diagnostics command."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from dcs_copilot_protocol import AudioFormat

from dcs_copilot.config import Settings
from dcs_copilot.network.connection import CloudSessionConnection


@dataclass(frozen=True, slots=True)
class CloudProbeResult:
    connected: bool
    authenticated: bool
    detail: str


async def probe_cloud(settings: Settings, *, timeout: float = 1.0) -> CloudProbeResult:
    try:
        connection = CloudSessionConnection(
            url=settings.cloud_url,
            access_token=settings.access_token,
            device_id=settings.device_id,
            audio_format=AudioFormat(
                sample_rate=settings.audio_sample_rate,
                channels=settings.audio_channels,
                chunk_ms=settings.audio_chunk_ms,
            ),
            queue_size=1,
            handshake_timeout_seconds=min(timeout, 5.0),
        )
    except ValueError as exc:
        return CloudProbeResult(False, False, str(exc))
    stop = asyncio.Event()
    task = asyncio.create_task(connection.run_once(stop), name="cloud-probe")
    ready = await connection.wait_ready(timeout=timeout)
    detail = "connected" if ready else "unavailable"
    if not ready and task.done():
        exception = task.exception()
        if exception is not None:
            detail = f"unavailable ({exception})"
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    except Exception as exc:  # noqa: BLE001 - diagnostics reports boundary failures
        if not ready:
            detail = f"unavailable ({exc})"
    return CloudProbeResult(ready, ready, detail)
