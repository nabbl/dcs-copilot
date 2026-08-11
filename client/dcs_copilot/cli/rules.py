"""CLI diagnostics for deterministic rules and configuration checks."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from dcs_copilot.config import Settings
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.events import SpeechPolicy
from dcs_copilot.state.models import AircraftState, CanopyState, FlapState, GearState
from dcs_copilot.state.store import AircraftStateStore


@dataclass(frozen=True, slots=True)
class CheckItem:
    label: str
    passed: bool
    detail: str


async def _state_store(settings: Settings, wait: float) -> AircraftStateStore | None:
    path = DcsBiosControlRegistry.discover(settings.dcs_bios_path)
    if path is None:
        print("DCS-BIOS control JSON not found.")
        return None
    registry = DcsBiosControlRegistry.from_path(path)
    client = DcsBiosClient(
        multicast_group=settings.multicast_group,
        port=settings.port,
        interface=settings.interface,
        stale_timeout=settings.stale_timeout,
        registry=registry,
    )
    store = AircraftStateStore(
        registry,
        client=client,
        value_stale_timeout=settings.value_stale_timeout,
        speech_policy=SpeechPolicy(settings.speech_mode),
    )
    try:
        await client.listen_for(wait)
        store.refresh()
        return store
    finally:
        client.close()


def run_rules(settings: Settings, wait: float, *, active_only: bool = False) -> int:
    store = asyncio.run(_state_store(settings, wait))
    if store is None:
        return 2
    print(f"{'RULE':34} {'MODE':7} {'STATUS':10} REASON")
    for diagnostic in store.rule_engine.diagnostics(
        store.current,
        store.history,
        now=time.monotonic(),
    ):
        if active_only and diagnostic.status != "ACTIVE":
            continue
        print(
            f"{diagnostic.rule_id[:34]:34} "
            f"{diagnostic.metadata['minimum_mode'][:7]:7} "
            f"{diagnostic.status[:10]:10} "
            f"{diagnostic.reason}"
        )
    return 0


def run_rule_explain(settings: Settings, wait: float, rule_id: str) -> int:
    store = asyncio.run(_state_store(settings, wait))
    if store is None:
        return 2
    rule = store.rule_engine.rule_by_id(rule_id)
    if rule is None:
        print(f"Unknown rule: {rule_id}")
        return 2
    diagnostic = next(
        item
        for item in store.rule_engine.diagnostics(
            store.current,
            store.history,
            now=time.monotonic(),
        )
        if item.rule_id == rule_id
    )
    metadata = diagnostic.metadata
    print(f"Rule: {rule.id}")
    print(f"Mode: {metadata['minimum_mode']}")
    print(f"Severity: {rule.severity.value}")
    print(f"Feasibility: {metadata['feasibility']}")
    print(f"Risk: {metadata['false_positive_risk']}")
    print(f"Category: {metadata['category']}")
    print(f"Status: {diagnostic.status}")
    print(f"Reason: {diagnostic.reason}")
    if metadata["description"]:
        print(f"Description: {metadata['description']}")
    print(f"Source: {metadata['source_reference']}")
    if rule.required_fields:
        print("Required fields:")
        telemetry = store.current.telemetry()
        for field in sorted(rule.required_fields):
            value = telemetry.get(field)
            if value is None or not value.usable:
                print(f"✗ {field} unavailable")
            else:
                print(f"✓ {field} = {value.value}")
    return 0


def run_carrier_launch_check(settings: Settings, wait: float) -> int:
    store = asyncio.run(_state_store(settings, wait))
    if store is None:
        return 2
    state = store.current
    items = carrier_launch_check(state)
    print("Carrier Launch Check\n")
    for item in items:
        mark = "✓" if item.passed else "✗"
        print(f"{mark} {item.label}{'' if item.passed else f' — {item.detail}'}")
    ready = all(item.passed for item in items)
    print(f"\n{'READY' if ready else 'NOT READY'}")
    return 0 if ready else 1


def carrier_launch_check(state: AircraftState) -> tuple[CheckItem, ...]:
    return (
        _check_bool("Wings spread", "wing_fold_spread", state, expected=True),
        _check_enum("Canopy closed", state.canopy_state.value, CanopyState.CLOSED),
        _check_bool("Seat armed", "ejection_seat_armed", state, expected=True),
        _check_bool("OBOGS on", "obogs_on", state, expected=True),
        _check_enum("Flaps HALF", state.flap_position.value, FlapState.HALF),
        _check_bool("Takeoff trim confirmed", "takeoff_trim_confirmed", state, expected=True),
        _check_bool("Hook up", "hook_position", state, expected=False),
        _check_number_max("Speedbrake retracted", state.speed_brake.value, 0.05),
        _check_enum("Gear down", state.gear_position.value, GearState.DOWN),
    )


def _check_bool(
    label: str,
    field: str,
    state: AircraftState,
    *,
    expected: bool,
) -> CheckItem:
    telemetry = state.telemetry()[field]
    if not telemetry.usable:
        return CheckItem(label, False, "unavailable")
    return CheckItem(
        label,
        bool(telemetry.value) is expected,
        f"expected {expected}, got {telemetry.value}",
    )


def _check_enum(label: str, value: object, expected: object) -> CheckItem:
    if value is None:
        return CheckItem(label, False, "unavailable")
    return CheckItem(label, value == expected, f"expected {expected}, got {value}")


def _check_number_max(label: str, value: object, maximum: float) -> CheckItem:
    if not isinstance(value, (int, float)):
        return CheckItem(label, False, "unavailable")
    return CheckItem(label, value <= maximum, f"expected <= {maximum}, got {value}")


__all__ = [
    "carrier_launch_check",
    "run_carrier_launch_check",
    "run_rule_explain",
    "run_rules",
]
