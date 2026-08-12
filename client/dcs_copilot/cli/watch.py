"""Meaningful decoded DCS-BIOS control change console."""

from __future__ import annotations

import asyncio
from collections.abc import Collection

from dcs_copilot.config import Settings
from dcs_copilot.dcs.bios_client import ControlChange, DcsBiosClient

from .status import _load_registry


async def _watch(
    settings: Settings,
    *,
    module: str | None,
    controls: Collection[str],
) -> int:
    registry, error = _load_registry(settings)
    if registry is None:
        print(f"Cannot watch controls: {error}")
        return 2

    requested = set(controls)

    def display(change: ControlChange) -> None:
        definition = change.control
        if module and definition.module != module:
            return
        if requested and definition.identifier not in requested:
            return
        print(f"{definition.qualified_name} = {change.value!r}", flush=True)

    client = DcsBiosClient(
        multicast_group=settings.multicast_group,
        port=settings.port,
        interface=settings.interface,
        stale_timeout=settings.stale_timeout,
        registry=registry,
    )
    client.add_change_callback(display)
    stop = asyncio.Event()
    try:
        await client.run(stop)
    except asyncio.CancelledError:
        pass
    return 0


def run_watch(
    settings: Settings,
    *,
    module: str | None,
    controls: Collection[str],
) -> int:
    try:
        return asyncio.run(_watch(settings, module=module, controls=controls))
    except KeyboardInterrupt:
        return 130
