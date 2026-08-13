from __future__ import annotations

import asyncio
from types import TracebackType

import pytest
from dcs_copilot.network.connection import (
    CloudConnectionError,
    CloudSessionConnection,
    validate_cloud_url,
)
from dcs_copilot_protocol import AudioFormat, ControlMessage, MediaKind, MediaPacket


class FakeTransport:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[str | bytes] = asyncio.Queue()
        self.sent: list[str | bytes] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent.append(payload)

    async def receive(self) -> str | bytes:
        return await self.incoming.get()

    async def close(self) -> None:
        return None


class FakeTransportContext:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport

    async def __aenter__(self) -> FakeTransport:
        return self.transport

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


def test_connection_handshake_uplink_and_downlink() -> None:
    async def scenario() -> tuple[list[str | bytes], list[bytes], list[str]]:
        transport = FakeTransport()
        await transport.incoming.put(ControlMessage("hello").to_json())
        await transport.incoming.put(
            ControlMessage(
                "connection.status",
                {"authenticated": True, "session_active": False},
            ).to_json()
        )
        await transport.incoming.put(
            ControlMessage(
                "connection.status",
                {"authenticated": True, "session_active": True},
            ).to_json()
        )
        await transport.incoming.put(
            ControlMessage(
                "error",
                {
                    "code": "voice_pipeline_failed",
                    "detail": "speech was not recognized",
                    "fatal": False,
                },
                correlation_id="turn-id",
            ).to_json()
        )
        output = MediaPacket(MediaKind.AUDIO_OUTPUT, 1, 1, b"reply")
        await transport.incoming.put(output.to_bytes())
        played: list[bytes] = []
        diagnostics: list[str] = []

        async def play(payload: bytes) -> None:
            played.append(payload)

        connection = CloudSessionConnection(
            url="ws://localhost/v2/realtime",
            access_token="token",
            device_id="device",
            audio_format=AudioFormat(),
            transport_factory=lambda _url: FakeTransportContext(transport),
            on_audio_output=play,
            on_diagnostic=diagnostics.append,
        )
        stop = asyncio.Event()
        task = asyncio.create_task(connection.run_once(stop))
        assert await connection.wait_ready(timeout=1)
        assert connection.send_control("ptt.start", {})
        assert connection.send_audio(b"pcm")
        assert await connection.drain(timeout=1)
        for _ in range(100):
            if len(transport.sent) >= 4 and played:
                break
            await asyncio.sleep(0)
        stop.set()
        await task
        return transport.sent, played, diagnostics

    sent, played, diagnostics = asyncio.run(scenario())
    controls = [
        ControlMessage.from_json(item) for item in sent if isinstance(item, str)
    ]
    assert [item.type for item in controls[:3]] == [
        "authenticate",
        "session.start",
        "ptt.start",
    ]
    session_start = controls[1]
    assert session_start.payload["input_audio"]["sample_rate"] == 16_000
    assert session_start.payload["output_audio"]["sample_rate"] == 24_000
    media = [MediaPacket.from_bytes(item) for item in sent if isinstance(item, bytes)]
    assert media[0].kind is MediaKind.AUDIO_INPUT
    assert media[0].payload == b"pcm"
    assert played == [b"reply"]
    assert any(line.startswith("Send: authenticate ") for line in diagnostics)
    assert any(line.startswith("Send: session.start ") for line in diagnostics)
    assert any(line.startswith("Send: ptt.start ") for line in diagnostics)
    assert any(line.startswith("Receive: connection.status ") for line in diagnostics)
    assert any(
        line.startswith("Error: cloud ")
        and "code=voice_pipeline_failed" in line
        and "detail=speech was not recognized" in line
        for line in diagnostics
    )
    assert all("token" not in line for line in diagnostics)


def test_cloud_url_requires_tls_except_on_loopback() -> None:
    validate_cloud_url("ws://127.0.0.1:8000/v2/realtime")
    validate_cloud_url("ws://[::1]:8000/v2/realtime")
    validate_cloud_url("wss://copilot.example/v2/realtime")
    with pytest.raises(ValueError, match="localhost"):
        validate_cloud_url("ws://copilot.example/v2/realtime")


def test_client_handshake_has_a_timeout() -> None:
    async def scenario() -> None:
        transport = FakeTransport()
        await transport.incoming.put(ControlMessage("hello").to_json())
        connection = CloudSessionConnection(
            url="ws://localhost/v2/realtime",
            access_token="token",
            device_id="device",
            audio_format=AudioFormat(),
            handshake_timeout_seconds=0.01,
            transport_factory=lambda _url: FakeTransportContext(transport),
        )
        with pytest.raises(CloudConnectionError, match="timed out"):
            await connection.run_once(asyncio.Event())

    asyncio.run(scenario())


def test_connection_gets_a_fresh_access_token_for_each_handshake() -> None:
    async def scenario() -> list[str]:
        tokens = iter(("first-token", "second-token"))
        seen: list[str] = []

        async def provide_token() -> str:
            value = next(tokens)
            seen.append(value)
            return value

        connection = CloudSessionConnection(
            url="ws://localhost/v2/realtime",
            access_token="bootstrap-token",
            access_token_provider=provide_token,
            device_id="device",
            audio_format=AudioFormat(),
        )
        for _ in range(2):
            transport = FakeTransport()
            await transport.incoming.put(ControlMessage("hello").to_json())
            await transport.incoming.put(
                ControlMessage(
                    "connection.status",
                    {"authenticated": True, "session_active": False},
                ).to_json()
            )
            await transport.incoming.put(
                ControlMessage(
                    "connection.status",
                    {"authenticated": True, "session_active": True},
                ).to_json()
            )
            connection._transport_factory = lambda _url, current=transport: (
                FakeTransportContext(current)
            )
            stop = asyncio.Event()
            task = asyncio.create_task(connection.run_once(stop))
            assert await connection.wait_ready(timeout=1)
            stop.set()
            await task
        return seen

    assert asyncio.run(scenario()) == ["first-token", "second-token"]
