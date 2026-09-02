"""Persistent authenticated cloud session with bounded non-blocking media queue."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import uuid4

from dcs_copilot_protocol import (
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
    ProtocolError,
)

from .transport import RealtimeTransport, open_websocket_transport

LOGGER = logging.getLogger(__name__)
OutboundPayload = str | bytes
TransportFactory = Callable[[str], AbstractAsyncContextManager[RealtimeTransport]]
AccessTokenProvider = Callable[[], Awaitable[str]]
DiagnosticCallback = Callable[[str], None]


class CloudConnectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CloudConnectionStatus:
    connected: bool
    authenticated: bool
    session_active: bool
    detail: str


class CloudSessionConnection:
    def __init__(
        self,
        *,
        url: str,
        access_token: str,
        device_id: str,
        audio_format: AudioFormat,
        output_audio_format: AudioFormat | None = None,
        queue_size: int = 256,
        handshake_timeout_seconds: float = 5.0,
        reconnect_max_seconds: float = 10.0,
        transport_factory: TransportFactory = open_websocket_transport,
        access_token_provider: AccessTokenProvider | None = None,
        on_status: Callable[[CloudConnectionStatus], None] | None = None,
        on_control: Callable[[ControlMessage], None] | None = None,
        on_audio_output: Callable[[bytes], Awaitable[None]] | None = None,
        on_diagnostic: DiagnosticCallback | None = None,
    ) -> None:
        validate_cloud_url(url)
        if not access_token:
            raise ValueError("DCS_COPILOT_ACCESS_TOKEN cannot be empty")
        if not device_id:
            raise ValueError("DCS_COPILOT_DEVICE_ID cannot be empty")
        if queue_size <= 0:
            raise ValueError("AUDIO_QUEUE_SIZE must be greater than zero")
        if handshake_timeout_seconds <= 0:
            raise ValueError("cloud handshake timeout must be greater than zero")
        self.url = url
        self.access_token = access_token
        self.device_id = device_id
        self.audio_format = audio_format
        self.output_audio_format = output_audio_format or AudioFormat(
            sample_rate=24_000,
            channels=audio_format.channels,
            chunk_ms=audio_format.chunk_ms,
        )
        self.handshake_timeout_seconds = handshake_timeout_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self._transport_factory = transport_factory
        self._access_token_provider = access_token_provider
        self._on_status = on_status
        self._on_control = on_control
        self._on_audio_output = on_audio_output
        self._on_diagnostic = on_diagnostic
        self._audio_queue_limit = queue_size
        # Reserve capacity for ptt.end and other control frames even when a slow
        # uplink has filled the audio allowance. FIFO ordering remains intact.
        self._outbound: asyncio.Queue[OutboundPayload] = asyncio.Queue(
            maxsize=queue_size + 16
        )
        self._ready = asyncio.Event()
        self._sequence = 0
        self._session_id: str | None = None
        self._session_generation = 0
        self.dropped_audio_chunks = 0

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def session_generation(self) -> int:
        return self._session_generation

    async def wait_ready(self, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def drain(self, timeout: float = 1.0) -> bool:
        """Wait briefly for already queued frames to reach the active transport."""

        try:
            await asyncio.wait_for(self._outbound.join(), timeout=timeout)
        except TimeoutError:
            return False
        return True

    async def run(self, stop: asyncio.Event) -> None:
        delay = 0.5
        while not stop.is_set():
            try:
                await self.run_once(stop)
                delay = 0.5
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect isolates transport failures
                self._set_disconnected(f"cloud unavailable: {exc}")
                LOGGER.warning("cloud connection failed: %s", exc)
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(max(0.5, delay * 2), self.reconnect_max_seconds)

    async def run_once(self, stop: asyncio.Event) -> None:
        async with self._transport_factory(self.url) as transport:
            await self._handshake(transport)
            writer = asyncio.create_task(self._writer(transport), name="cloud-writer")
            receiver = asyncio.create_task(
                self._receiver(transport), name="cloud-receiver"
            )
            stopper = asyncio.create_task(stop.wait(), name="cloud-stop")
            try:
                done, _pending = await asyncio.wait(
                    (writer, receiver, stopper),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receiver in done:
                    receiver.result()
                if writer in done:
                    writer.result()
            finally:
                writer.cancel()
                receiver.cancel()
                stopper.cancel()
                await asyncio.gather(writer, receiver, stopper, return_exceptions=True)
                if self._session_id is not None:
                    try:
                        await transport.send_text(
                            ControlMessage(
                                "session.end", {"session_id": self._session_id}
                            ).to_json()
                        )
                        self._diagnose("Send: session.end")
                    except Exception as exc:  # noqa: BLE001 - connection is already closing
                        LOGGER.debug("session.end could not be sent: %s", exc)
                self._set_disconnected("disconnected")

    def send_control(self, message_type: str, payload: dict[str, object]) -> bool:
        return self.send_message(ControlMessage(message_type, payload))

    def send_message(self, message: ControlMessage) -> bool:
        if not self.ready:
            if not _is_stream_message(message.type):
                self._diagnose(f"Error: {message.type} not queued; cloud unavailable")
            return False
        queued = self._enqueue(
            message.to_json(),
            stream=_is_stream_message(message.type),
            audio=False,
        )
        if not queued and not _is_stream_message(message.type):
            self._diagnose(f"Error: {message.type} not queued; outbound queue full")
        return queued

    def send_audio(self, audio: bytes) -> bool:
        if not self.ready or not audio:
            return False
        packet = MediaPacket(
            MediaKind.AUDIO_INPUT,
            self._sequence,
            int(time.monotonic() * 1000),
            audio,
        )
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return self._enqueue(packet.to_bytes(), stream=True, audio=True)

    async def _handshake(self, transport: RealtimeTransport) -> None:
        hello = await self._receive_handshake_control(transport)
        if hello.type != "hello":
            raise CloudConnectionError("cloud did not send hello")
        self._notify_status(True, False, False, "connected; authenticating")

        access_token = (
            await self._access_token_provider()
            if self._access_token_provider is not None
            else self.access_token
        )
        if not access_token:
            raise CloudConnectionError("access token provider returned an empty token")
        authentication = ControlMessage(
            "authenticate",
            {
                "access_token": access_token,
                "device_id": self.device_id,
            },
        )
        await transport.send_text(authentication.to_json())
        self._diagnose_control("Send", authentication)
        authenticated = await self._receive_handshake_control(transport)
        self._require_status(authenticated, authenticated=True)

        self._session_id = str(uuid4())
        session = ControlMessage(
            "session.start",
            {
                "session_id": self._session_id,
                "input_audio": self.audio_format.to_dict(),
                "output_audio": self.output_audio_format.to_dict(),
            },
        )
        await transport.send_text(session.to_json())
        self._diagnose_control("Send", session)
        started = await self._receive_handshake_control(transport)
        self._require_status(started, authenticated=True, session_active=True)
        self._session_generation += 1
        self._ready.set()
        self._notify_status(True, True, True, "connected and authenticated")

    async def _writer(self, transport: RealtimeTransport) -> None:
        while True:
            payload = await self._outbound.get()
            try:
                if isinstance(payload, str):
                    await transport.send_text(payload)
                    self._diagnose_control("Send", ControlMessage.from_json(payload))
                else:
                    await transport.send_bytes(payload)
            finally:
                self._outbound.task_done()

    async def _receiver(self, transport: RealtimeTransport) -> None:
        while True:
            payload = await transport.receive()
            if isinstance(payload, str):
                message = ControlMessage.from_json(payload)
                self._diagnose_control("Receive", message)
                if message.type == "error":
                    LOGGER.warning("cloud protocol error: %s", message.payload)
                if self._on_control is not None:
                    self._on_control(message)
                continue
            packet = MediaPacket.from_bytes(payload)
            if packet.kind is not MediaKind.AUDIO_OUTPUT:
                raise ProtocolError("cloud sent a non-output media packet")
            if self._on_audio_output is not None:
                await self._on_audio_output(packet.payload)

    async def _receive_control(self, transport: RealtimeTransport) -> ControlMessage:
        payload = await transport.receive()
        if not isinstance(payload, str):
            raise CloudConnectionError("expected a control message during handshake")
        message = ControlMessage.from_json(payload)
        self._diagnose_control("Receive", message)
        if message.type == "error":
            raise CloudConnectionError(str(message.payload.get("code", "error")))
        return message

    async def _receive_handshake_control(
        self, transport: RealtimeTransport
    ) -> ControlMessage:
        try:
            return await asyncio.wait_for(
                self._receive_control(transport),
                timeout=self.handshake_timeout_seconds,
            )
        except TimeoutError as exc:
            raise CloudConnectionError("cloud handshake timed out") from exc

    @staticmethod
    def _require_status(
        message: ControlMessage,
        *,
        authenticated: bool,
        session_active: bool | None = None,
    ) -> None:
        if message.type != "connection.status":
            raise CloudConnectionError("expected connection.status")
        if message.payload.get("authenticated") is not authenticated:
            raise CloudConnectionError("cloud authentication failed")
        if (
            session_active is not None
            and message.payload.get("session_active") is not session_active
        ):
            raise CloudConnectionError("cloud session did not start")

    def _enqueue(self, payload: OutboundPayload, *, stream: bool, audio: bool) -> bool:
        if stream and self._outbound.qsize() >= self._audio_queue_limit:
            if audio:
                self.dropped_audio_chunks += 1
            return False
        try:
            self._outbound.put_nowait(payload)
        except asyncio.QueueFull:
            if audio:
                self.dropped_audio_chunks += 1
            return False
        return True

    def _set_disconnected(self, detail: str) -> None:
        self._ready.clear()
        self._session_id = None
        self._drain_outbound()
        self._notify_status(False, False, False, detail)

    def _drain_outbound(self) -> None:
        while True:
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._outbound.task_done()

    def _notify_status(
        self,
        connected: bool,
        authenticated: bool,
        session_active: bool,
        detail: str,
    ) -> None:
        if self._on_status is not None:
            self._on_status(
                CloudConnectionStatus(connected, authenticated, session_active, detail)
            )

    def _diagnose_control(self, direction: str, message: ControlMessage) -> None:
        if _is_stream_message(message.type):
            return
        prefix = (
            "Error: cloud"
            if message.type == "error"
            else f"{direction}: {message.type}"
        )
        parts = [prefix, f"id={message.message_id[:8]}"]
        if message.correlation_id is not None:
            parts.append(f"correlation={message.correlation_id[:8]}")
        if message.type == "event":
            event_type = message.payload.get("event_type")
            if isinstance(event_type, str):
                parts.append(f"event={event_type}")
            for name in ("audio_chunks", "audio_bytes", "duration_ms"):
                value = message.payload.get(name)
                if isinstance(value, int):
                    parts.append(f"{name}={value}")
        elif message.type == "error":
            code = message.payload.get("code")
            if isinstance(code, str):
                parts.append(f"code={code}")
            detail = message.payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                parts.append(f"detail={_bounded_line(detail)}")
        self._diagnose(" ".join(parts))

    def _diagnose(self, line: str) -> None:
        if self._on_diagnostic is not None:
            self._on_diagnostic(line)


def validate_cloud_url(url: str) -> None:
    """Require TLS on public networks; permit explicit loopback/private LAN URLs."""

    parsed = urlparse(url)
    if parsed.scheme == "wss" and parsed.hostname:
        return
    if parsed.scheme != "ws" or not parsed.hostname:
        raise ValueError("DCS_COPILOT_CLOUD_URL must use wss:// or loopback ws://")
    host = parsed.hostname
    is_private = host == "localhost"
    if not is_private:
        try:
            address = ipaddress.ip_address(host)
            is_private = (
                address.is_loopback or address.is_private or address.is_link_local
            )
        except ValueError:
            is_private = False
    if not is_private:
        raise ValueError(
            "unencrypted ws:// is allowed only for localhost or private LANs"
        )


def _bounded_line(value: str, limit: int = 240) -> str:
    line = " ".join(value.split())
    return line if len(line) <= limit else f"{line[: limit - 3]}..."


def _is_stream_message(message_type: str) -> bool:
    return message_type.startswith("telemetry.") or message_type == "coach.telemetry"
