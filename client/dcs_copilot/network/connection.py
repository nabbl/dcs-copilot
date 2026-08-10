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
        on_status: Callable[[CloudConnectionStatus], None] | None = None,
        on_control: Callable[[ControlMessage], None] | None = None,
        on_audio_output: Callable[[bytes], Awaitable[None]] | None = None,
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
        self._on_status = on_status
        self._on_control = on_control
        self._on_audio_output = on_audio_output
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
                    except Exception as exc:  # noqa: BLE001 - connection is already closing
                        LOGGER.debug("session.end could not be sent: %s", exc)
                self._set_disconnected("disconnected")

    def send_control(self, message_type: str, payload: dict[str, object]) -> bool:
        return self.send_message(ControlMessage(message_type, payload))

    def send_message(self, message: ControlMessage) -> bool:
        if not self.ready:
            return False
        return self._enqueue(message.to_json(), audio=False)

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
        return self._enqueue(packet.to_bytes(), audio=True)

    async def _handshake(self, transport: RealtimeTransport) -> None:
        hello = await self._receive_handshake_control(transport)
        if hello.type != "hello":
            raise CloudConnectionError("cloud did not send hello")
        self._notify_status(True, False, False, "connected; authenticating")

        authentication = ControlMessage(
            "authenticate",
            {
                "access_token": self.access_token,
                "device_id": self.device_id,
            },
        )
        await transport.send_text(authentication.to_json())
        authenticated = await self._receive_handshake_control(transport)
        self._require_status(authenticated, authenticated=True)

        self._session_id = str(uuid4())
        session = ControlMessage(
            "session.start",
            {
                "session_id": self._session_id,
                # `audio` remains for protocol-v1 gateways built before output
                # format negotiation was introduced.
                "audio": self.audio_format.to_dict(),
                "input_audio": self.audio_format.to_dict(),
                "output_audio": self.output_audio_format.to_dict(),
            },
        )
        await transport.send_text(session.to_json())
        started = await self._receive_handshake_control(transport)
        self._require_status(started, authenticated=True, session_active=True)
        self._session_generation += 1
        self._ready.set()
        self._notify_status(True, True, True, "connected and authenticated")

    async def _writer(self, transport: RealtimeTransport) -> None:
        while True:
            payload = await self._outbound.get()
            if isinstance(payload, str):
                await transport.send_text(payload)
            else:
                await transport.send_bytes(payload)

    async def _receiver(self, transport: RealtimeTransport) -> None:
        while True:
            payload = await transport.receive()
            if isinstance(payload, str):
                message = ControlMessage.from_json(payload)
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

    @staticmethod
    async def _receive_control(transport: RealtimeTransport) -> ControlMessage:
        payload = await transport.receive()
        if not isinstance(payload, str):
            raise CloudConnectionError("expected a control message during handshake")
        message = ControlMessage.from_json(payload)
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

    def _enqueue(self, payload: OutboundPayload, *, audio: bool) -> bool:
        if audio and self._outbound.qsize() >= self._audio_queue_limit:
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


def validate_cloud_url(url: str) -> None:
    """Require TLS except for an explicitly local development gateway."""

    parsed = urlparse(url)
    if parsed.scheme == "wss" and parsed.hostname:
        return
    if parsed.scheme != "ws" or not parsed.hostname:
        raise ValueError("DCS_COPILOT_CLOUD_URL must use wss:// or loopback ws://")
    host = parsed.hostname
    is_loopback = host == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise ValueError("unencrypted ws:// is allowed only for localhost development")
