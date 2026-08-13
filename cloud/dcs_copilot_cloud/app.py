"""FastAPI application and WebSocket transport adapter."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from dcs_copilot_protocol import (
    PROTOCOL_VERSION,
    ControlMessage,
    MediaKind,
    MediaPacket,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy.exc import SQLAlchemyError

from .accounts import ACCOUNT_TOOL_NAMES, AccountStore, AccountToolExecutor
from .aircraft.raw import RawTelemetryKey
from .auth import AuthService
from .auth_api import auth_router
from .config import LOCAL_DEVELOPMENT_SIGNING_KEY, CloudSettings
from .database import Database
from .events.models import CloudAircraftEvent, CloudManagedEvent
from .events.policy import SpeechMode, SpeechPolicy
from .greetings import CockpitGreetingSelector
from .providers import build_provider_bundle
from .session import (
    CompletedUtterance,
    RealtimeSession,
    SessionResult,
    UtteranceReceipt,
)
from .state.store import AircraftStateStore
from .telemetry import TelemetryBatch, TelemetryIngress
from .tools import (
    AIRCRAFT_TOOL_NAMES,
    AircraftToolRequest,
    BackendAircraftToolExecutor,
    ToolProtocolError,
)
from .voice import (
    PipecatVoicePipeline,
    VoiceAnnouncement,
    VoicePipeline,
    VoicePipelineError,
    VoiceTurn,
)

LOGGER = logging.getLogger("uvicorn.error")


VoicePipelineFactory = Callable[[CloudSettings], VoicePipeline]


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(
    settings: CloudSettings | None = None,
    *,
    voice_pipeline_factory: VoicePipelineFactory | None = None,
) -> FastAPI:
    configured = settings or CloudSettings.from_env()
    if not is_loopback_host(configured.host):
        if configured.dev_access_token:
            raise ValueError(
                "DCS_COPILOT_DEV_TOKEN must be empty on a non-loopback host"
            )
        if configured.auth_signing_key == LOCAL_DEVELOPMENT_SIGNING_KEY:
            raise ValueError(
                "replace DCS_COPILOT_AUTH_SIGNING_KEY on a non-loopback host"
            )
    if configured.handshake_timeout_seconds <= 0:
        raise ValueError("CLOUD_HANDSHAKE_TIMEOUT_SECONDS must be greater than zero")
    if configured.max_utterance_seconds <= 0:
        raise ValueError("CLOUD_MAX_UTTERANCE_SECONDS must be greater than zero")
    if configured.telemetry_stale_seconds <= 0:
        raise ValueError("CLOUD_TELEMETRY_STALE_SECONDS must be greater than zero")
    pipeline_factory = voice_pipeline_factory or (
        lambda current: PipecatVoicePipeline(build_provider_bundle(current))
    )
    database = Database(configured.database_url)
    auth = AuthService(
        database,
        signing_key=configured.auth_signing_key,
        access_token_seconds=configured.auth_access_token_seconds,
        refresh_token_days=configured.auth_refresh_token_days,
        dev_access_token=configured.dev_access_token,
    )
    accounts = AccountStore(database)
    cleanup_tasks: set[asyncio.Task[None]] = set()

    def cleanup_finished(task: asyncio.Task[None]) -> None:
        cleanup_tasks.discard(task)
        if task.cancelled():
            return
        if exception := task.exception():
            LOGGER.warning("flight-session disconnect cleanup failed: %s", exception)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await database.initialize()
        try:
            yield
        finally:
            if cleanup_tasks:
                await asyncio.gather(*tuple(cleanup_tasks), return_exceptions=True)
            await database.close()

    app = FastAPI(
        title="DCS Copilot Cloud",
        version="0.7.0",
        lifespan=lifespan,
    )
    app.include_router(auth_router(auth))
    received_utterances: deque[UtteranceReceipt] = deque(maxlen=1_000)
    app.state.received_utterances = received_utterances
    app.state.database = database
    app.state.auth = auth
    app.state.accounts = accounts

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "protocol_version": PROTOCOL_VERSION,
            "ai_inference": configured.voice_configured
            or voice_pipeline_factory is not None,
            "voice_pipeline": "pipecat",
            "proactive_events": True,
            "accounts": True,
            "memory": True,
            "habits": True,
        }

    @app.websocket("/v2/realtime")
    async def realtime(websocket: WebSocket) -> None:
        await websocket.accept()
        session = RealtimeSession(
            auth.verify_access_token,
            max_utterance_seconds=configured.max_utterance_seconds,
        )
        send_lock = asyncio.Lock()
        voice: VoicePipeline | None = None
        response_task: asyncio.Task[None] | None = None
        response_event_id: str | None = None
        active_event_ids: dict[str, None] = {}
        greeting_selector = CockpitGreetingSelector()
        output_sequence = 0
        telemetry = TelemetryIngress()
        aircraft_state = AircraftStateStore(
            value_stale_timeout=configured.telemetry_stale_seconds
        )
        aircraft_tools = BackendAircraftToolExecutor(aircraft_state)

        async def send_control(message: ControlMessage) -> None:
            async with send_lock:
                await websocket.send_text(message.to_json())

        async def request_copilot_tool(
            tool: str, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            if tool in AIRCRAFT_TOOL_NAMES:
                try:
                    await refresh_aircraft_state()
                    return aircraft_tools.execute(
                        AircraftToolRequest.create(tool, arguments)
                    )
                except ToolProtocolError as exc:
                    return {
                        "available": False,
                        "error": {
                            "code": "invalid_aircraft_tool",
                            "detail": str(exc),
                        },
                    }
            if tool in ACCOUNT_TOOL_NAMES:
                result = await AccountToolExecutor(accounts, session.user_id).request(
                    tool, arguments
                )
                if tool == "set_chatter_level":
                    preference = result.get("preference")
                    if isinstance(preference, dict) and preference.get("aircraft") in {
                        None,
                        telemetry.aircraft,
                    }:
                        apply_speech_mode(preference.get("value"))
                return result
            return {
                "available": False,
                "error": {
                    "code": "tool_not_allowlisted",
                    "detail": "the requested tool is not available",
                },
            }

        async def interrupt_response() -> bool:
            nonlocal response_event_id, response_task
            if response_task is None or response_task.done():
                response_task = None
                response_event_id = None
                return False
            if voice is not None:
                await voice.interrupt()
            response_task.cancel()
            await asyncio.gather(response_task, return_exceptions=True)
            response_task = None
            response_event_id = None
            return True

        async def reset_assistant() -> None:
            nonlocal voice
            await interrupt_response()
            active_event_ids.clear()
            if voice is not None:
                previous_voice = voice
                voice = None
                await previous_voice.close()

        async def stream_audio(payload: bytes) -> None:
            nonlocal output_sequence
            packet = MediaPacket(
                kind=MediaKind.AUDIO_OUTPUT,
                sequence=output_sequence,
                timestamp_ms=int(time.monotonic() * 1000),
                payload=payload,
            )
            output_sequence = (output_sequence + 1) & 0xFFFFFFFF
            async with send_lock:
                await websocket.send_bytes(packet.to_bytes())

        async def run_voice_turn(utterance: CompletedUtterance) -> None:
            nonlocal voice
            LOGGER.info(
                "voice turn started: session=%s correlation=%s audio_bytes=%d",
                utterance.session_id,
                utterance.correlation_id,
                len(utterance.audio),
            )
            try:
                if voice is None:
                    voice = pipeline_factory(configured)
                result = await voice.respond(
                    VoiceTurn(
                        utterance.audio,
                        utterance.input_format,
                        utterance.output_format,
                    ),
                    stream_audio,
                    request_copilot_tool,
                )
                await send_control(
                    ControlMessage(
                        "pilot.text",
                        {"text": result.transcript},
                        correlation_id=utterance.correlation_id,
                    )
                )
                await send_control(
                    ControlMessage(
                        "assistant.text",
                        {"text": result.response_text},
                        correlation_id=utterance.correlation_id,
                    )
                )
                LOGGER.info(
                    "voice turn completed: session=%s correlation=%s "
                    "transcript_chars=%d response_chars=%d",
                    utterance.session_id,
                    utterance.correlation_id,
                    len(result.transcript),
                    len(result.response_text),
                )
            except asyncio.CancelledError:
                LOGGER.info(
                    "voice turn interrupted: session=%s correlation=%s",
                    utterance.session_id,
                    utterance.correlation_id,
                )
                raise
            except (ValueError, VoicePipelineError) as exc:
                LOGGER.warning(
                    "voice turn failed: session=%s correlation=%s error=%s",
                    utterance.session_id,
                    utterance.correlation_id,
                    exc,
                )
                await send_control(
                    ControlMessage(
                        "error",
                        {
                            "code": "voice_pipeline_failed",
                            "detail": str(exc),
                            "fatal": False,
                        },
                        correlation_id=utterance.correlation_id,
                    )
                )

        async def run_announcement(
            event: CloudAircraftEvent,
            *,
            correlation_id: str,
        ) -> None:
            nonlocal response_event_id, voice
            try:
                if voice is None:
                    voice = pipeline_factory(configured)
                if (
                    session.input_audio_format is None
                    or session.output_audio_format is None
                ):
                    raise VoicePipelineError("session audio format is unavailable")
                response = await voice.announce(
                    VoiceAnnouncement(
                        event.message,
                        session.input_audio_format,
                        session.output_audio_format,
                    ),
                    stream_audio,
                )
                await send_control(
                    ControlMessage(
                        "assistant.text",
                        {
                            "text": response,
                            "proactive": True,
                            "event_id": event.event_id,
                        },
                        correlation_id=correlation_id,
                    )
                )
            except asyncio.CancelledError:
                raise
            except (ValueError, VoicePipelineError) as exc:
                LOGGER.warning("proactive announcement failed: %s", exc)
                await send_control(
                    ControlMessage(
                        "error",
                        {
                            "code": "proactive_voice_failed",
                            "detail": str(exc),
                            "fatal": False,
                        },
                        correlation_id=correlation_id,
                    )
                )
            finally:
                if response_event_id == event.event_id:
                    response_event_id = None

        async def run_cockpit_welcome(
            aircraft: str,
            *,
            correlation_id: str,
        ) -> None:
            nonlocal voice
            try:
                if voice is None:
                    voice = pipeline_factory(configured)
                if (
                    session.input_audio_format is None
                    or session.output_audio_format is None
                ):
                    raise VoicePipelineError("session audio format is unavailable")
                response = await voice.announce(
                    VoiceAnnouncement(
                        greeting_selector.choose(aircraft),
                        session.input_audio_format,
                        session.output_audio_format,
                    ),
                    stream_audio,
                )
                await send_control(
                    ControlMessage(
                        "assistant.text",
                        {
                            "text": response,
                            "proactive": True,
                            "kind": "cockpit_welcome",
                            "aircraft": aircraft,
                        },
                        correlation_id=correlation_id,
                    )
                )
            except asyncio.CancelledError:
                raise
            except (ValueError, VoicePipelineError) as exc:
                LOGGER.warning("cockpit welcome failed: %s", exc)
                await send_control(
                    ControlMessage(
                        "error",
                        {
                            "code": "cockpit_welcome_failed",
                            "detail": str(exc),
                            "fatal": False,
                        },
                        correlation_id=correlation_id,
                    )
                )

        async def persist_pending_summaries() -> None:
            for summary in aircraft_state.flight_stats.pending:
                if session.user_id is None:
                    aircraft_state.flight_stats.acknowledge(summary.summary_id)
                    continue
                try:
                    await accounts.ingest_flight_summary(session.user_id, summary)
                except SQLAlchemyError:
                    LOGGER.exception("semantic flight summary storage failed")
                    return
                aircraft_state.flight_stats.acknowledge(summary.summary_id)

        def apply_speech_mode(value: object) -> None:
            if not isinstance(value, str):
                return
            try:
                mode = SpeechMode(value.upper())
            except ValueError:
                return
            aircraft_state.event_manager.speech_policy = SpeechPolicy(mode=mode)

        async def load_speech_policy(aircraft: str) -> None:
            aircraft_state.event_manager.speech_policy = SpeechPolicy()
            if session.user_id is None:
                return
            try:
                preferences = await accounts.get_preferences(
                    session.user_id,
                    aircraft=None,
                )
            except SQLAlchemyError:
                LOGGER.exception("aircraft speech preference lookup failed")
                return
            selected: object = None
            for preference in preferences:
                if preference.get("key") != "chatter_level":
                    continue
                preference_aircraft = preference.get("aircraft")
                if preference_aircraft is None:
                    selected = preference.get("value")
                elif preference_aircraft == aircraft:
                    selected = preference.get("value")
                    break
            apply_speech_mode(selected)

        async def handle_managed_event(managed: CloudManagedEvent) -> None:
            nonlocal response_event_id, response_task
            if not managed.publish:
                return
            event = managed.event
            if event.status != "RAISED":
                active_event_ids.pop(event.event_id, None)
                if response_event_id == event.event_id:
                    await interrupt_response()
                return
            if event.event_id in active_event_ids:
                return
            active_event_ids[event.event_id] = None
            if len(active_event_ids) > 1_000:
                del active_event_ids[next(iter(active_event_ids))]
            if not managed.speak or session.ptt_active:
                return
            if response_task is not None and not response_task.done():
                if event.severity not in {"WARNING", "CRITICAL"}:
                    return
                await interrupt_response()
            response_event_id = event.event_id
            response_task = asyncio.create_task(
                run_announcement(event, correlation_id=event.event_id),
                name=f"proactive-{event.event_id}",
            )

        async def refresh_aircraft_state() -> None:
            if not telemetry.ready or telemetry.aircraft is None:
                return
            _state, events = aircraft_state.update(
                aircraft=telemetry.aircraft,
                connected=True,
                now=time.monotonic(),
            )
            for managed in events:
                await handle_managed_event(managed)
            await persist_pending_summaries()

        def raw_key(value: Any) -> RawTelemetryKey:
            identity = value.identity
            return RawTelemetryKey(
                identity.module,
                identity.identifier,
                identity.output_type,
                identity.output_index,
            )

        async def apply_telemetry_batch(
            batch: TelemetryBatch,
            *,
            correlation_id: str,
        ) -> None:
            nonlocal response_task
            now = time.monotonic()
            if batch.kind == "reset":
                aircraft_state.update(aircraft=None, connected=False, now=now)
                await persist_pending_summaries()
                aircraft_state.raw.reset()
                aircraft_state.event_manager.speech_policy = SpeechPolicy()
                await reset_assistant()
                if session.user_id is not None and session.session_id is not None:
                    await accounts.update_flight_aircraft(
                        session.user_id,
                        client_session_id=session.session_id,
                        aircraft=batch.aircraft,
                    )
                return
            if batch.kind == "snapshot":
                await load_speech_policy(batch.aircraft)
                for entry in batch.catalog:
                    aircraft_state.raw.catalog_register(
                        raw_key(entry),
                        max_value=entry.integer_max,
                    )
            for decoded in batch.values:
                key = raw_key(decoded)
                if decoded.available and decoded.value is not None:
                    # Client monotonic clocks are not comparable across machines.
                    aircraft_state.raw.update(key, decoded.value, received_at=now)
                else:
                    aircraft_state.raw.mark_unavailable(key)
            if batch.kind == "snapshot" and (
                response_task is None or response_task.done()
            ):
                response_task = asyncio.create_task(
                    run_cockpit_welcome(
                        batch.aircraft,
                        correlation_id=correlation_id,
                    ),
                    name="cockpit-welcome",
                )
            await refresh_aircraft_state()

        await send_control(session.hello())
        try:
            while True:
                if session.session_id is None:
                    try:
                        incoming = await asyncio.wait_for(
                            websocket.receive(),
                            timeout=configured.handshake_timeout_seconds,
                        )
                    except TimeoutError:
                        await send_control(
                            ControlMessage(
                                "error",
                                {"code": "handshake_timeout", "fatal": True},
                            )
                        )
                        await websocket.close(code=4408)
                        break
                else:
                    incoming = await websocket.receive()
                if incoming["type"] == "websocket.disconnect":
                    break
                try:
                    if incoming.get("text") is not None:
                        message = ControlMessage.from_json(incoming["text"])
                        if message.type.startswith("telemetry."):
                            if session.session_id is None:
                                result = SessionResult(
                                    responses=(
                                        ControlMessage(
                                            "error",
                                            {
                                                "code": "session_not_active",
                                                "fatal": False,
                                            },
                                            correlation_id=message.message_id,
                                        ),
                                    )
                                )
                            else:
                                batch = telemetry.accept(message)
                                if batch is not None:
                                    await apply_telemetry_batch(
                                        batch,
                                        correlation_id=message.message_id,
                                    )
                                result = SessionResult()
                        else:
                            if message.type in {"assistant.interrupt", "ptt.start"}:
                                await interrupt_response()
                            result = session.handle_control(message)
                    elif incoming.get("bytes") is not None:
                        packet = MediaPacket.from_bytes(incoming["bytes"])
                        result = session.handle_media(packet)
                    else:
                        continue
                except UnsupportedProtocolVersion as exc:
                    result = SessionResult(
                        responses=(
                            ControlMessage(
                                "error",
                                {
                                    "code": "unsupported_protocol_version",
                                    "detail": str(exc),
                                    "fatal": True,
                                },
                            ),
                        ),
                        close_code=4400,
                    )
                except ProtocolError as exc:
                    result = SessionResult(
                        responses=(
                            ControlMessage(
                                "error",
                                {
                                    "code": "invalid_message",
                                    "detail": str(exc),
                                    "fatal": False,
                                },
                            ),
                        )
                    )
                if result.lifecycle is not None and session.user_id is not None:
                    lifecycle = result.lifecycle
                    if lifecycle.action == "started":
                        assert session.device_id is not None
                        await accounts.start_flight(
                            session.user_id,
                            client_session_id=lifecycle.session_id,
                            device_id=session.device_id,
                        )
                    elif lifecycle.action == "ended":
                        await accounts.end_flight(
                            session.user_id,
                            client_session_id=lifecycle.session_id,
                        )
                for response in result.responses:
                    await send_control(response)
                if result.receipt is not None:
                    received_utterances.append(result.receipt)
                    LOGGER.info(
                        "utterance received: session=%s bytes=%d chunks=%d duration_ms=%d",
                        result.receipt.session_id,
                        result.receipt.audio_bytes,
                        result.receipt.audio_chunks,
                        result.receipt.duration_ms,
                    )
                if result.utterance is not None:
                    response_task = asyncio.create_task(
                        run_voice_turn(result.utterance),
                        name=f"voice-turn-{result.utterance.session_id}",
                    )
                if result.close_code is not None:
                    await websocket.close(code=result.close_code)
                    break
        except WebSocketDisconnect:
            pass
        finally:
            aircraft_state.update(
                aircraft=None,
                connected=False,
                now=time.monotonic(),
            )
            await persist_pending_summaries()
            aircraft_state.raw.reset()
            telemetry.disconnect()
            if session.user_id is not None and session.session_id is not None:
                cleanup = asyncio.create_task(
                    accounts.end_flight(
                        session.user_id,
                        client_session_id=session.session_id,
                    ),
                    name=f"end-flight-{session.session_id}",
                )
                cleanup_tasks.add(cleanup)
                cleanup.add_done_callback(cleanup_finished)
            await interrupt_response()
            if voice is not None:
                await voice.close()

    return app


app = create_app()
