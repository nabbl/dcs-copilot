"""Meaningful decoded DCS-BIOS control change console."""

from __future__ import annotations

import asyncio
from collections.abc import Collection

from dcs_copilot.config import Settings
from dcs_copilot.dcs.bios_client import ControlChange, DcsBiosClient
from dcs_copilot.rules.base import RuleTransition
from dcs_copilot.state.store import AircraftStateStore, NormalizedStateChange

from .status import _load_registry


async def _watch(
    settings: Settings,
    *,
    raw: bool,
    module: str | None,
    controls: Collection[str],
) -> int:
    registry, error = _load_registry(settings)
    if registry is None:
        print(f"Cannot watch controls: {error}")
        return 2

    requested = set(controls)

    def display_raw(change: ControlChange) -> None:
        definition = change.control
        if module and definition.module != module:
            return
        if requested and definition.identifier not in requested:
            return
        print(f"{definition.qualified_name} = {change.value!r}", flush=True)

    def display_normalized(change: NormalizedStateChange) -> None:
        print(
            f"{change.field} = {change.new_value!r} [{change.status}]",
            flush=True,
        )

    def display_rule(transition: RuleTransition) -> None:
        print(
            f"RULE {transition.type}: {transition.issue.rule_id} "
            f"[{transition.issue.severity}] {transition.issue.message}",
            flush=True,
        )

    client = DcsBiosClient(
        multicast_group=settings.multicast_group,
        port=settings.port,
        interface=settings.interface,
        stale_timeout=settings.stale_timeout,
        registry=registry,
    )
    state_store = AircraftStateStore(
        registry,
        client=client,
        value_stale_timeout=settings.value_stale_timeout,
    )
    if raw:
        client.add_change_callback(display_raw)
    else:
        state_store.add_change_callback(display_normalized)
        state_store.rule_engine.add_transition_callback(display_rule)
    stop = asyncio.Event()
    try:
        await client.run(stop)
    except asyncio.CancelledError:
        pass
    return 0


def run_watch(
    settings: Settings,
    *,
    raw: bool,
    module: str | None,
    controls: Collection[str],
) -> int:
    try:
        return asyncio.run(_watch(settings, raw=raw, module=module, controls=controls))
    except KeyboardInterrupt:
        return 130
