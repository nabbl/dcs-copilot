"""FastAPI application and WebSocket transport adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable

from dcs_copilot_protocol import (
    PROTOCOL_VERSION,
    ControlMessage,
    MediaKind,
    MediaPacket,
    ProtocolError,
    UnsupportedProtocolVersion,
)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .config import CloudSettings
from .providers import build_provider_bundle
from .session import (
    CompletedUtterance,
    RealtimeSession,
    SessionResult,
    UtteranceReceipt,
)
from .tools import LocalAircraftToolBroker
from .voice import PipecatVoicePipeline, VoicePipeline, VoicePipelineError, VoiceTurn

LOGGER = logging.getLogger("uvicorn.error")


VoicePipelineFactory = Callable[[CloudSettings], VoicePipeline]


def create_app(
    settings: CloudSettings | None = None,
    *,
    voice_pipeline_factory: VoicePipelineFactory | None = None,
) -> FastAPI:
    configured = settings or CloudSettings.from_env()
    if not configured.dev_access_token:
        raise ValueError("DCS_COPILOT_DEV_TOKEN cannot be empty")
    if configured.handshake_timeout_seconds <= 0:
        raise ValueError("CLOUD_HANDSHAKE_TIMEOUT_SECONDS must be greater than zero")
    if configured.max_utterance_seconds <= 0:
        raise ValueError("CLOUD_MAX_UTTERANCE_SECONDS must be greater than zero")
    if configured.aircraft_tool_timeout_seconds <= 0:
        raise ValueError("CLOUD_AIRCRAFT_TOOL_TIMEOUT_SECONDS must be greater than zero")
    pipeline_factory = voice_pipeline_factory or (
        lambda current: PipecatVoicePipeline(build_provider_bundle(current))
    )
    app = FastAPI(title="DCS Copilot Cloud", version="0.2.0")
    received_utterances: deque[UtteranceReceipt] = deque(maxlen=1_000)
    app.state.received_utterances = received_utterances

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "protocol_version": PROTOCOL_VERSION,
            "ai_inference": configured.voice_configured
            or voice_pipeline_factory is not None,
            "voice_pipeline": "pipecat",
        }

    @app.websocket("/v1/realtime")
    async def realtime(websocket: WebSocket) -> None:
        await websocket.accept()
        session = RealtimeSession(
            configured.dev_access_token,
            max_utterance_seconds=configured.max_utterance_seconds,
        )
        send_lock = asyncio.Lock()
        voice: VoicePipeline | None = None
        response_task: asyncio.Task[None] | None = None
        output_sequence = 0

        async def send_control(message: ControlMessage) -> None:
            async with send_lock:
                await websocket.send_text(message.to_json())

        aircraft_tools = LocalAircraftToolBroker(
            send_control,
            timeout_seconds=configured.aircraft_tool_timeout_seconds,
        )

        async def interrupt_response() -> None:
            nonlocal response_task
            if voice is not None:
                await voice.interrupt()
            if response_task is not None and not response_task.done():
                response_task.cancel()
                await asyncio.gather(response_task, return_exceptions=True)
            response_task = None

        async def run_voice_turn(utterance: CompletedUtterance) -> None:
            nonlocal voice, output_sequence
            try:
                if voice is None:
                    voice = pipeline_factory(configured)

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

                result = await voice.respond(
                    VoiceTurn(
                        utterance.audio,
                        utterance.input_format,
                        utterance.output_format,
                    ),
                    stream_audio,
                    aircraft_tools.request,
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
            aircraft_tools.disconnect()
            await interrupt_response()
            if voice is not None:
                await voice.close()

    return app


app = create_app()
