"""Combined local DCS monitor and cloud audio peripheral runtime."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from dcs_copilot_protocol import (
    AircraftChanged,
    AudioFormat,
    CockpitEntered,
    ControlMessage,
    FlightSummary,
)

from .audio.feedback import mute_tone, unmute_tone
from .audio.portaudio import PortAudioCapture, PortAudioPlayback
from .cli.status import _load_registry
from .config import Settings
from .dcs.bios_client import DcsBiosClient
from .desktop.activity import ConversationActivity
from .events import ManagedAircraftEvent, SpeechPolicy
from .input.controller import PttSessionController
from .input.ptt import (
    GlobalFunctionKeyHotkey,
    GlobalFunctionKeyPTT,
    GlobalJoystickButtonHotkey,
    GlobalJoystickButtonPTT,
    PTTUnavailableError,
)
from .network.connection import CloudConnectionStatus, CloudSessionConnection
from .state.store import AircraftStateStore, NormalizedStateChange
from .tools import AircraftToolExecutor

LOGGER = logging.getLogger(__name__)


async def run_client_runtime(
    settings: Settings,
    *,
    stdin_ptt: bool = False,
    access_token_provider: Callable[[], Awaitable[str]] | None = None,
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
    store = (
        AircraftStateStore(
            registry,
            client=dcs_client,
            value_stale_timeout=settings.value_stale_timeout,
            speech_policy=SpeechPolicy(settings.speech_mode),
        )
        if registry is not None
        else None
    )
    aircraft_tools = AircraftToolExecutor(store)
    summary_requests: dict[str, str] = {}
    conversation_activity = ConversationActivity()
    pending_cockpit_welcome: str | None = None
    cockpit_welcome_ready = False

    def send_flight_summary(summary: FlightSummary) -> bool:
        message = summary.to_control()
        if not connection.send_message(message):
            return False
        summary_requests[message.message_id] = summary.summary_id
        return True

    def status_changed(status: CloudConnectionStatus) -> None:
        print(f"Cloud: {status.detail}")
        if not status.connected:
            summary_requests.clear()
            conversation_activity.reset()
        if status.session_active and store is not None:
            connection.send_message(
                AircraftChanged(store.current.aircraft).to_control()
            )
            send_pending_cockpit_welcome()
            for summary in store.flight_stats.pending:
                send_flight_summary(summary)

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
        elif message.type == "event" and message.payload.get("event_type") == (
            "flight.summary.accepted"
        ):
            summary_id = message.payload.get("summary_id")
            request_summary_id = (
                summary_requests.pop(message.correlation_id, None)
                if message.correlation_id is not None
                else None
            )
            if (
                store is not None
                and isinstance(summary_id, str)
                and request_summary_id == summary_id
            ):
                store.flight_stats.acknowledge(summary_id)
                for request_id, pending_id in tuple(summary_requests.items()):
                    if pending_id == summary_id:
                        del summary_requests[request_id]
        else:
            for line in conversation_activity.accept(message):
                print(line, flush=True)

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
    )
    controller = PttSessionController(connection, capture, playback, on_notice=print)
    published_event_ids: set[str] = set()

    def send_pending_cockpit_welcome() -> None:
        nonlocal pending_cockpit_welcome
        if (
            cockpit_welcome_ready
            and pending_cockpit_welcome is not None
            and connection.send_message(
                CockpitEntered(pending_cockpit_welcome).to_control()
            )
        ):
            pending_cockpit_welcome = None

    async def prepare_cockpit_welcome(aircraft: str | None) -> None:
        nonlocal cockpit_welcome_ready
        await controller.reset()
        if aircraft is None or aircraft != pending_cockpit_welcome:
            return
        cockpit_welcome_ready = True
        send_pending_cockpit_welcome()

    def proactive_event(managed: ManagedAircraftEvent) -> None:
        if not managed.publish:
            return
        event = managed.event
        if event.status == "RAISED" and managed.speak and controller.active:
            LOGGER.info(
                "proactive event suppressed while PTT is active: %s",
                event.rule_id,
            )
            return
        if event.status != "RAISED" and event.event_id not in published_event_ids:
            return
        if connection.send_message(event.to_control()):
            if event.status == "RAISED":
                published_event_ids.add(event.event_id)
            else:
                published_event_ids.discard(event.event_id)
            return
        published_event_ids.discard(event.event_id)
        if event.status == "RAISED":
            LOGGER.info(
                "proactive event retained locally while cloud is unavailable: %s",
                event.rule_id,
            )

    if store is not None:
        store.event_manager.add_callback(proactive_event)

        def flight_summary_ready(summary: FlightSummary) -> None:
            if not send_flight_summary(summary):
                LOGGER.info("flight summary retained until cloud reconnects")

        store.flight_stats.add_summary_callback(flight_summary_ready)

        def state_changed(change: NormalizedStateChange) -> None:
            nonlocal cockpit_welcome_ready, pending_cockpit_welcome
            if change.field == "aircraft":
                published_event_ids.clear()
                conversation_activity.reset()
                connection.send_message(AircraftChanged(change.new_value).to_control())
                pending_cockpit_welcome = (
                    change.new_value if isinstance(change.new_value, str) else None
                )
                cockpit_welcome_ready = False
                schedule(prepare_cockpit_welcome(pending_cockpit_welcome))

        store.add_change_callback(state_changed)

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

        def create() -> None:
            task = asyncio.create_task(coroutine)
            scheduled.add(task)
            task.add_done_callback(finished)

        loop.call_soon_threadsafe(create)

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

    telemetry_task = asyncio.create_task(
        dcs_client.run(stop), name="dcs-bios-telemetry"
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
        tasks = [telemetry_task, cloud_task]
        if ptt_task is not None:
            tasks.append(ptt_task)
        await asyncio.gather(*tasks)
    finally:
        if store is not None:
            store.flight_stats.finish()
            await connection.drain()
        stop.set()
        if ptt_input is not None:
            ptt_input.stop()
            await asyncio.sleep(0)
        if mute_input is not None:
            mute_input.stop()
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
