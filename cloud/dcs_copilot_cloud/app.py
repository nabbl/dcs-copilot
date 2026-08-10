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
    AircraftEvent,
    ControlMessage,
    MediaKind,
    MediaPacket,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .accounts import ACCOUNT_TOOL_NAMES, AccountStore, AccountToolExecutor
from .auth import AuthService
from .auth_api import auth_router
from .config import LOCAL_DEVELOPMENT_SIGNING_KEY, CloudSettings
from .database import Database
from .providers import build_provider_bundle
from .session import (
    CompletedUtterance,
    RealtimeSession,
    SessionResult,
    UtteranceReceipt,
)
from .tools import AIRCRAFT_TOOL_NAMES, LocalAircraftToolBroker
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
    if configured.aircraft_tool_timeout_seconds <= 0:
        raise ValueError(
            "CLOUD_AIRCRAFT_TOOL_TIMEOUT_SECONDS must be greater than zero"
        )
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
        version="0.6.0",
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
        }

    @app.websocket("/v1/realtime")
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
        output_sequence = 0

        async def send_control(message: ControlMessage) -> None:
            async with send_lock:
                await websocket.send_text(message.to_json())

        aircraft_tools = LocalAircraftToolBroker(
            send_control,
            timeout_seconds=configured.aircraft_tool_timeout_seconds,
        )

        async def request_copilot_tool(
            tool: str, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            if tool in AIRCRAFT_TOOL_NAMES:
                return await aircraft_tools.request(tool, arguments)
            if tool in ACCOUNT_TOOL_NAMES:
                return await AccountToolExecutor(accounts, session.user_id).request(
                    tool, arguments
                )
            return {
                "available": False,
                "error": {
                    "code": "tool_not_allowlisted",
                    "detail": "the requested tool is not available",
                },
            }

        async def interrupt_response() -> None:
            nonlocal response_event_id, response_task
            if voice is not None:
                await voice.interrupt()
            if response_task is not None and not response_task.done():
                response_task.cancel()
                await asyncio.gather(response_task, return_exceptions=True)
            response_task = None
            response_event_id = None

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
                        "assistant.text",
                        {"text": result.response_text},
                        correlation_id=utterance.correlation_id,
                    )
                )
                LOGGER.info(
                    "voice turn completed: session=%s transcript_chars=%d response_chars=%d",
                    utterance.session_id,
                    len(result.transcript),
                    len(result.response_text),
                )
            except asyncio.CancelledError:
                raise
            except (ValueError, VoicePipelineError) as exc:
                LOGGER.warning("voice turn failed: %s", exc)
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
            event: AircraftEvent,
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
                        if message.type == "tool.result":
                            aircraft_tools.resolve(message)
                            result = SessionResult()
                        elif message.type in {"event.raised", "event.resolved"}:
                            event = AircraftEvent.from_control(message)
                            if not session.authenticated or session.session_id is None:
                                result = session.handle_control(message)
                            elif message.type == "event.resolved":
                                active_event_ids.pop(event.event_id, None)
                                if response_event_id == event.event_id:
                                    await interrupt_response()
                                result = SessionResult()
                            elif event.event_id in active_event_ids:
                                result = SessionResult()
                            elif session.ptt_active:
                                active_event_ids[event.event_id] = None
                                result = SessionResult()
                            elif response_task is not None and not response_task.done():
                                active_event_ids[event.event_id] = None
                                if event.severity in {"WARNING", "CRITICAL"}:
                                    await interrupt_response()
                                    response_event_id = event.event_id
                                    response_task = asyncio.create_task(
                                        run_announcement(
                                            event,
                                            correlation_id=message.message_id,
                                        ),
                                        name=f"proactive-{event.event_id}",
                                    )
                                result = SessionResult()
                            else:
                                active_event_ids[event.event_id] = None
                                response_event_id = event.event_id
                                response_task = asyncio.create_task(
                                    run_announcement(
                                        event,
                                        correlation_id=message.message_id,
                                    ),
                                    name=f"proactive-{event.event_id}",
                                )
                                result = SessionResult()
                            if len(active_event_ids) > 1_000:
                                del active_event_ids[next(iter(active_event_ids))]
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
                    elif lifecycle.action == "aircraft_changed":
                        await accounts.update_flight_aircraft(
                            session.user_id,
                            client_session_id=lifecycle.session_id,
                            aircraft=lifecycle.aircraft,
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
            aircraft_tools.disconnect()
            await interrupt_response()
            if voice is not None:
                await voice.close()

    return app


app = create_app()
