"""Bounded DCS Copilot health snapshot."""

from __future__ import annotations

import asyncio
import sys

from dcs_copilot.audio.devices import inspect_audio_devices
from dcs_copilot.config import Settings
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.spatial_export import DcsSpatialClient
from dcs_copilot.diagnostics.cloud import CloudProbeResult, probe_cloud
from dcs_copilot.diagnostics.resources import ResourceSnapshot, format_bytes
from dcs_copilot.input.ptt import split_hotkey


def _load_registry(
    settings: Settings,
) -> tuple[DcsBiosControlRegistry | None, str | None]:
    try:
        path = DcsBiosControlRegistry.discover(settings.dcs_bios_path)
    except FileNotFoundError as exc:
        return None, str(exc)
    if path is None:
        return None, (
            "DCS-BIOS control JSON not found; install DCS-BIOS from the desktop "
            "app or set DCS_BIOS_PATH (see docs/dcs-bios.md)"
        )
    registry = DcsBiosControlRegistry.from_path(path)
    return registry, None


async def collect_status(settings: Settings, wait: float) -> tuple[list[str], int]:
    resource_start = ResourceSnapshot.capture()
    cloud_task = (
        asyncio.create_task(
            probe_cloud(settings, timeout=min(2.0, max(0.25, wait))),
            name="cloud-diagnostics",
        )
        if wait > 0
        else None
    )
    registry, registry_error = _load_registry(settings)
    client = DcsBiosClient(
        multicast_group=settings.multicast_group,
        port=settings.port,
        interface=settings.interface,
        stale_timeout=settings.stale_timeout,
        registry=registry,
    )
    spatial_stop = asyncio.Event()
    spatial = DcsSpatialClient(
        host=settings.spatial_export_host,
        port=settings.spatial_export_port,
        stale_timeout=settings.spatial_export_stale_timeout,
        cockpit_state_provider=lambda: client.connected,
    )
    spatial_task = asyncio.create_task(spatial.run(spatial_stop))
    socket_error: str | None = None
    try:
        await client.listen_for(wait)
    except OSError as exc:
        socket_error = str(exc)
    finally:
        # Preserve values used to build the report before close invalidates them.
        connected = client.connected
        frame_age = client.frame_age
        aircraft = client.current_aircraft
        parser_errors = client.parser.error_count
        available_outputs = len(client.decoded_snapshot())
        active_outputs = len(client.active_definitions())
        client.close()
        spatial_stop.set()
        spatial_result = await asyncio.gather(spatial_task, return_exceptions=True)
    resource_end = ResourceSnapshot.capture()
    cloud = (
        await cloud_task
        if cloud_task is not None
        else CloudProbeResult(False, False, "not probed; use --wait 0.25 or longer")
    )

    if socket_error:
        dcs_status = f"socket error ({socket_error})"
    else:
        dcs_status = "connected" if connected else "disconnected"
    age_text = "never" if frame_age is None else f"{frame_age * 1000:.0f} ms ago"
    registry_text = str(registry.control_count) if registry else "0"
    module_text = str(registry.module_count) if registry else "0"
    metadata_status = (
        "ready" if registry is not None else f"unavailable ({registry_error})"
    )
    if registry and registry.load_errors:
        metadata_status = f"degraded ({len(registry.load_errors)} file errors)"
    resource_sample_seconds = resource_end.wall_time - resource_start.wall_time
    cpu_status = (
        f"{resource_start.cpu_percent_until(resource_end):.3f}%"
        if resource_sample_seconds >= 0.05
        else "unavailable (use --wait 0.1 or longer)"
    )
    ptt_status = _input_binding_status(
        settings.copilot_ptt_key,
        settings.copilot_ptt_device,
        settings.copilot_ptt_button,
    )
    mute_status = _input_binding_status(
        settings.assistant_mute_key,
        settings.assistant_mute_device,
        settings.assistant_mute_button,
    )
    audio_devices = inspect_audio_devices(
        settings.audio_input_device, settings.audio_output_device
    )
    spatial_observation = spatial.last_observation
    spatial_error = next(
        (str(value) for value in spatial_result if isinstance(value, Exception)),
        None,
    )
    spatial_lines = _coach_status_lines(
        spatial_observation.capabilities if spatial_observation else None,
        cockpit_available=connected,
        error=spatial_error,
    )

    lines = [
        f"DCS-BIOS: {dcs_status}",
        f"Aircraft: {aircraft or 'unavailable'}",
        f"Last frame: {age_text}",
        f"Controls loaded: {registry_text}",
        f"Modules loaded: {module_text}",
        f"Control metadata: {metadata_status}",
        f"Parser errors: {parser_errors}",
        f"Active catalog outputs: {active_outputs}",
        f"Available decoded outputs: {available_outputs}",
        *spatial_lines,
        f"Cloud: {cloud.detail}",
        f"Authenticated: {'yes' if cloud.authenticated else 'no'}",
        f"PTT: {ptt_status}",
        f"Mute: {mute_status}",
        f"Microphone: {audio_devices.input_detail} (not opened)",
        f"Output: {audio_devices.output_detail} (not opened)",
        f"Client CPU during sample: {cpu_status}",
        f"Client RAM: {format_bytes(resource_end.resident_memory_bytes)}",
        "AI inference running locally: NO",
    ]
    return lines, 0 if not socket_error else 1


def _coach_status_lines(
    capabilities, *, cockpit_available: bool, error: str | None
) -> list[str]:
    ownship = bool(capabilities and capabilities.ownship_export)
    world = bool(capabilities and capabilities.world_object_export)
    spatial = ownship and world
    world_detail = "AVAILABLE" if world else "BLOCKED"
    if capabilities is None:
        world_detail = "UNAVAILABLE"
    if error:
        world_detail = f"UNAVAILABLE ({error})"
    return [
        "MARA Coach",
        f"Ownship telemetry: {'AVAILABLE' if ownship else 'UNAVAILABLE'}",
        f"Cockpit telemetry: {'AVAILABLE' if cockpit_available else 'UNAVAILABLE'}",
        f"World object export: {world_detail}",
        f"Formation Coach: {'AVAILABLE' if spatial else 'UNAVAILABLE'}",
        f"CASE I Pattern Coach: {'AVAILABLE' if spatial else 'UNAVAILABLE'}",
        f"Carrier Approach: {'AVAILABLE' if spatial else 'UNAVAILABLE'}",
        f"Procedure Coach: {'AVAILABLE' if cockpit_available else 'UNAVAILABLE'}",
    ]


def _input_binding_status(
    key: str,
    device: int | None,
    button: int | None,
) -> str:
    if (device is None) != (button is None):
        return "invalid (controller device and button must both be configured)"
    if device is not None and button is not None:
        binding = f"controller {device}, button {button}"
        return binding if sys.platform == "win32" else f"{binding} (Windows only)"
    try:
        split_hotkey(key)
    except ValueError as exc:
        return f"invalid ({exc})"
    return key if sys.platform == "win32" else f"{key} (Windows only)"


def run_status(settings: Settings, wait: float) -> int:
    lines, exit_code = asyncio.run(collect_status(settings, wait))
    print("\n".join(lines))
    return exit_code
