"""Combined local DCS monitor and cloud audio peripheral runtime."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from dcs_copilot_protocol import AudioFormat, CoachTelemetry, ControlMessage

from .audio.feedback import mute_tone, unmute_tone
from .audio.portaudio import PortAudioCapture, PortAudioPlayback
from .cli.status import _load_registry
from .config import Settings
from .dcs.bios_client import DcsBiosClient
from .dcs.spatial_export import DcsSpatialClient
from .dcs.spatial_recording import SpatialRecordingWriter
from .dcs.text_output import DcsTextOutput
from .desktop.activity import ConversationActivity
from .input.controller import PttSessionController
from .input.ptt import (
    GlobalFunctionKeyHotkey,
    GlobalFunctionKeyPTT,
    GlobalJoystickButtonHotkey,
    GlobalJoystickButtonPTT,
    PTTUnavailableError,
)
from .network.connection import CloudConnectionStatus, CloudSessionConnection
from .telemetry import TelemetryPublisher

LOGGER = logging.getLogger(__name__)


async def run_client_runtime(
    settings: Settings,
    *,
    stdin_ptt: bool = False,
    access_token_provider: Callable[[], Awaitable[str]] | None = None,
    coach_recording_path: Path | None = None,
) -> int:
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
    muted_feedback = mute_tone(output_audio_format)
    unmuted_feedback = unmute_tone(output_audio_format)

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
    conversation_activity = ConversationActivity()
    dcs_text_output = DcsTextOutput()
    telemetry: TelemetryPublisher | None = None

    def emit_activity(line: str) -> None:
        print(line, flush=True)

    def status_changed(status: CloudConnectionStatus) -> None:
        emit_activity(f"Cloud: {status.detail}")
        if telemetry is not None:
            telemetry.set_session_active(status.session_active)
        if not status.connected:
            conversation_activity.reset()

    def control_received(message: ControlMessage) -> None:
        dcs_text_output.accept(message)
        for line in conversation_activity.accept(message):
            emit_activity(line)

    connection = CloudSessionConnection(
        url=settings.cloud_url,
        access_token=settings.access_token,
        device_id=settings.device_id,
        audio_format=input_audio_format,
        output_audio_format=output_audio_format,
        queue_size=settings.audio_queue_size,
        handshake_timeout_seconds=settings.cloud_handshake_timeout_seconds,
        reconnect_max_seconds=settings.cloud_reconnect_max_seconds,
        access_token_provider=access_token_provider,
        on_status=status_changed,
        on_control=control_received,
        on_audio_output=playback.play,
        on_diagnostic=emit_activity,
    )
    if registry is not None:
        telemetry = TelemetryPublisher(dcs_client, connection.send_message)
    recording = (
        SpatialRecordingWriter(coach_recording_path)
        if coach_recording_path is not None
        else None
    )

    def publish_spatial_observation(observation: CoachTelemetry) -> None:
        nonlocal recording
        if recording is not None:
            try:
                recording.write(observation)
            except (OSError, RuntimeError) as exc:
                LOGGER.error("Coach recording stopped: %s", exc)
                recording.close()
                recording = None
        connection.send_message(observation.to_control())

    spatial = DcsSpatialClient(
        host=settings.spatial_export_host,
        port=settings.spatial_export_port,
        stale_timeout=settings.spatial_export_stale_timeout,
        cockpit_state_provider=lambda: dcs_client.connected,
        on_observation=publish_spatial_observation,
    )
    controller = PttSessionController(
        connection, capture, playback, on_notice=emit_activity
    )

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
                LOGGER.error("input action failed: %s", exception)
                detail = " ".join(str(exception).split())
                emit_activity(f"Error: input action failed: {detail[:240]}")

        def create() -> None:
            task = asyncio.create_task(coroutine)
            scheduled.add(task)
            task.add_done_callback(finished)

        loop.call_soon_threadsafe(create)

    def aircraft_changed(_aircraft: str | None) -> None:
        conversation_activity.reset()
        schedule(controller.reset())

    dcs_client.add_aircraft_callback(aircraft_changed)

    ptt_input: GlobalFunctionKeyPTT | GlobalJoystickButtonPTT | None = None
    mute_input: GlobalFunctionKeyHotkey | GlobalJoystickButtonHotkey | None = None
    ptt_task: asyncio.Task[None] | None = None
    if stdin_ptt:
        if sys.platform == "win32":
            print("--stdin-ptt is intended for POSIX development terminals")
            return 2
        ptt_task = asyncio.create_task(
            _run_stdin_ptt(stop, controller), name="stdin-ptt"
        )
    else:

        def ptt_pressed() -> None:
            schedule(controller.press())

        def ptt_released() -> None:
            schedule(controller.release())

        async def toggle_assistant_mute() -> None:
            muted = await playback.toggle_muted(
                muted_feedback=muted_feedback,
                unmuted_feedback=unmuted_feedback,
            )
            print(f"Assistant audio {'muted' if muted else 'unmuted'}.")

        def mute_pressed() -> None:
            schedule(toggle_assistant_mute())

        if (
            settings.copilot_ptt_device is None
            and settings.assistant_mute_device is None
            and settings.copilot_ptt_key == settings.assistant_mute_key
        ):
            print("Mute hotkey unavailable: it cannot be the same as keyboard PTT.")
            return 2
        if (
            settings.copilot_ptt_device is not None
            and settings.assistant_mute_device == settings.copilot_ptt_device
            and settings.assistant_mute_button == settings.copilot_ptt_button
        ):
            print("Mute button unavailable: it cannot be the same as PTT.")
            return 2
        if (
            settings.copilot_ptt_device is not None
            and settings.copilot_ptt_button is not None
        ):
            ptt_input = GlobalJoystickButtonPTT(
                settings.copilot_ptt_device,
                settings.copilot_ptt_button,
                on_press=ptt_pressed,
                on_release=ptt_released,
            )
        else:
            ptt_input = GlobalFunctionKeyPTT(
                settings.copilot_ptt_key,
                on_press=ptt_pressed,
                on_release=ptt_released,
            )
        try:
            ptt_input.start()
        except (PTTUnavailableError, ValueError) as exc:
            print(f"PTT unavailable: {exc}")
            return 2
        if (
            settings.assistant_mute_device is not None
            and settings.assistant_mute_button is not None
        ):
            mute_input = GlobalJoystickButtonHotkey(
                settings.assistant_mute_device,
                settings.assistant_mute_button,
                on_press=mute_pressed,
            )
        else:
            mute_input = GlobalFunctionKeyHotkey(
                settings.assistant_mute_key,
                on_press=mute_pressed,
            )
        try:
            mute_input.start()
        except (PTTUnavailableError, ValueError) as exc:
            ptt_input.stop()
            print(f"Mute hotkey unavailable: {exc}")
            return 2

    if recording is not None:
        recording.open()
    telemetry_task = asyncio.create_task(
        dcs_client.run(stop), name="dcs-bios-telemetry"
    )
    spatial_task = asyncio.create_task(spatial.run(stop), name="dcs-spatial-export")
    telemetry_publish_task = (
        asyncio.create_task(telemetry.run(stop), name="cloud-telemetry-publisher")
        if telemetry is not None
        else None
    )
    cloud_task = asyncio.create_task(connection.run(stop), name="cloud-session")
    print("MARA voice is AI-generated.")
    ptt_label = (
        f"controller {settings.copilot_ptt_device}, button {settings.copilot_ptt_button}"
        if settings.copilot_ptt_device is not None
        else settings.copilot_ptt_key
    )
    mute_label = (
        f"controller {settings.assistant_mute_device}, "
        f"button {settings.assistant_mute_button}"
        if settings.assistant_mute_device is not None
        else settings.assistant_mute_key
    )
    print(
        f"DCS Copilot running; PTT {ptt_label}; mute {mute_label}. "
        "Press Ctrl-C to stop."
    )
    try:
        tasks = [telemetry_task, spatial_task, cloud_task]
        if telemetry_publish_task is not None:
            tasks.append(telemetry_publish_task)
        if ptt_task is not None:
            tasks.append(ptt_task)
        await asyncio.gather(*tasks)
    finally:
        stop.set()
        if ptt_input is not None:
            ptt_input.stop()
            await asyncio.sleep(0)
        if mute_input is not None:
            mute_input.stop()
            await asyncio.sleep(0)
        await controller.release()
        await playback.close()
        for task in (
            telemetry_task,
            spatial_task,
            telemetry_publish_task,
            cloud_task,
            ptt_task,
        ):
            if task is not None:
                task.cancel()
        for task in tuple(scheduled):
            task.cancel()
        await asyncio.gather(
            telemetry_task,
            spatial_task,
            *(task for task in (telemetry_publish_task,) if task is not None),
            cloud_task,
            *(task for task in (ptt_task, *scheduled) if task is not None),
            return_exceptions=True,
        )
        dcs_client.close()
        dcs_text_output.close()
        if recording is not None:
            recording.close()
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
