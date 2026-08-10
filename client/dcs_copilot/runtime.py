"""Combined local DCS monitor and cloud audio peripheral runtime."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Coroutine
from typing import Any

from dcs_copilot_protocol import AudioFormat, ControlMessage

from .audio.portaudio import PortAudioCapture, PortAudioPlayback
from .cli.status import _load_registry
from .config import Settings
from .dcs.bios_client import DcsBiosClient
from .input.controller import PttSessionController
from .input.ptt import GlobalFunctionKeyPTT, PTTUnavailableError
from .network.connection import CloudConnectionStatus, CloudSessionConnection
from .state.store import AircraftStateStore
from .tools import AircraftToolExecutor

LOGGER = logging.getLogger(__name__)


async def run_client_runtime(settings: Settings, *, stdin_ptt: bool = False) -> int:
    input_audio_format = AudioFormat(
        sample_rate=settings.audio_sample_rate,
        channels=settings.audio_channels,
        chunk_ms=settings.audio_chunk_ms,
    )
    output_audio_format = AudioFormat(
        sample_rate=settings.audio_output_sample_rate,
        channels=settings.audio_channels,
        chunk_ms=settings.audio_chunk_ms,
    )
    capture = PortAudioCapture(
        input_audio_format, device_index=settings.audio_input_device
    )
    playback = PortAudioPlayback(
        output_audio_format, device_index=settings.audio_output_device
    )

    registry, registry_error = _load_registry(settings)
    if registry is None:
        print(f"DCS-BIOS metadata unavailable: {registry_error}")
    dcs_client = DcsBiosClient(
        multicast_group=settings.multicast_group,
        port=settings.port,
        interface=settings.interface,
        stale_timeout=settings.stale_timeout,
        registry=registry,
    )
    store = (
        AircraftStateStore(
            registry,
            client=dcs_client,
            value_stale_timeout=settings.value_stale_timeout,
        )
        if registry is not None
        else None
    )
    aircraft_tools = AircraftToolExecutor(store)

    def status_changed(status: CloudConnectionStatus) -> None:
        print(f"Cloud: {status.detail}")

    def control_received(message: ControlMessage) -> None:
        if message.type == "tool.request":
            if not connection.send_message(aircraft_tools.handle_control(message)):
                LOGGER.warning("aircraft tool result could not be queued")
        elif message.type == "event" and message.payload.get("event_type") == (
            "utterance.received"
        ):
            print(
                "Cloud received utterance: "
                f"{message.payload.get('audio_bytes', 0)} bytes"
            )
        elif message.type == "assistant.text":
            text = message.payload.get("text")
            if isinstance(text, str):
                print(f"Copilot: {text}")

    connection = CloudSessionConnection(
        url=settings.cloud_url,
        access_token=settings.access_token,
        device_id=settings.device_id,
        audio_format=input_audio_format,
        output_audio_format=output_audio_format,
        queue_size=settings.audio_queue_size,
        handshake_timeout_seconds=settings.cloud_handshake_timeout_seconds,
        reconnect_max_seconds=settings.cloud_reconnect_max_seconds,
        on_status=status_changed,
        on_control=control_received,
        on_audio_output=playback.play,
    )
    controller = PttSessionController(connection, capture, playback, on_notice=print)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    scheduled: set[asyncio.Task[Any]] = set()

    def schedule(coroutine: Coroutine[Any, Any, object]) -> None:
        def finished(task: asyncio.Task[Any]) -> None:
            scheduled.discard(task)
            if task.cancelled():
                return
            exception = task.exception()
            if exception is not None:
                LOGGER.error("PTT action failed: %s", exception)

        def create() -> None:
            task = asyncio.create_task(coroutine)
            scheduled.add(task)
            task.add_done_callback(finished)

        loop.call_soon_threadsafe(create)

    hotkey: GlobalFunctionKeyPTT | None = None
    ptt_task: asyncio.Task[None] | None = None
    if stdin_ptt:
        if sys.platform == "win32":
            print("--stdin-ptt is intended for POSIX development terminals")
            return 2
        ptt_task = asyncio.create_task(
            _run_stdin_ptt(stop, controller), name="stdin-ptt"
        )
    else:
        hotkey = GlobalFunctionKeyPTT(
            settings.copilot_ptt_key,
            on_press=lambda: schedule(controller.press()),
            on_release=lambda: schedule(controller.release()),
        )
        try:
            hotkey.start()
        except (PTTUnavailableError, ValueError) as exc:
            print(f"PTT unavailable: {exc}")
            return 2

    telemetry_task = asyncio.create_task(
        dcs_client.run(stop), name="dcs-bios-telemetry"
    )
    cloud_task = asyncio.create_task(connection.run(stop), name="cloud-session")
    print("Copilot voice is AI-generated.")
    print(f"DCS Copilot running; PTT {settings.copilot_ptt_key}. Press Ctrl-C to stop.")
    try:
        tasks = [telemetry_task, cloud_task]
        if ptt_task is not None:
            tasks.append(ptt_task)
        await asyncio.gather(*tasks)
    finally:
        stop.set()
        if hotkey is not None:
            hotkey.stop()
            await asyncio.sleep(0)
        await controller.release()
        await playback.close()
        for task in (telemetry_task, cloud_task, ptt_task):
            if task is not None:
                task.cancel()
        for task in tuple(scheduled):
            task.cancel()
        await asyncio.gather(
            telemetry_task,
            cloud_task,
            *(task for task in (ptt_task, *scheduled) if task is not None),
            return_exceptions=True,
        )
        dcs_client.close()
    return 0


async def _run_stdin_ptt(stop: asyncio.Event, controller: PttSessionController) -> None:
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[None] = asyncio.Queue()

    def line_ready() -> None:
        sys.stdin.readline()
        lines.put_nowait(None)

    loop.add_reader(sys.stdin, line_ready)
    active = False
    print("Development PTT: press Enter to start/stop transmission.")
    try:
        while not stop.is_set():
            await lines.get()
            if active:
                await controller.release()
                active = False
            else:
                active = await controller.press()
    finally:
        loop.remove_reader(sys.stdin)
        await controller.release()
