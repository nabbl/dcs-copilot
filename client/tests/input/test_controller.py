from __future__ import annotations

import asyncio

from dcs_copilot.input.controller import PttSessionController


class FakeConnection:
    ready = True
    session_generation = 1

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def send_control(self, message_type: str, payload: dict[str, object]) -> bool:
        self.sent.append((message_type, payload))
        return True

    def send_audio(self, payload: bytes) -> bool:
        self.sent.append(("audio", payload))
        return True


class FakeCapture:
    def __init__(self) -> None:
        self.on_audio = None
        self.events: list[str] = []

    async def start(self, on_audio) -> None:
        self.events.append("capture.start")
        self.on_audio = on_audio
        on_audio(b"pcm")

    async def stop(self) -> None:
        self.events.append("capture.stop")


class FakePlayback:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def interrupt(self) -> None:
        self.events.append("playback.interrupt")


def test_ptt_starts_capture_and_release_is_authoritative_end() -> None:
    connection = FakeConnection()
    capture = FakeCapture()
    playback = FakePlayback()
    notices: list[str] = []
    controller = PttSessionController(  # type: ignore[arg-type]
        connection, capture, playback, on_notice=notices.append
    )

    async def scenario() -> None:
        assert await controller.press()
        assert controller.active
        assert await controller.release()
        assert not controller.active

    asyncio.run(scenario())
    assert playback.events == ["playback.interrupt"]
    assert capture.events == ["capture.start", "capture.stop"]
    assert [item[0] for item in connection.sent] == [
        "assistant.interrupt",
        "ptt.start",
        "audio",
        "ptt.end",
    ]
    assert notices == [
        "PTT: active",
        "PTT: released audio_chunks=1 audio_bytes=3 dropped=0",
    ]


def test_reconnect_during_ptt_does_not_leak_audio_into_new_session() -> None:
    connection = FakeConnection()
    capture = FakeCapture()
    controller = PttSessionController(  # type: ignore[arg-type]
        connection, capture, FakePlayback()
    )

    async def scenario() -> None:
        assert await controller.press()
        connection.session_generation = 2
        capture.on_audio(b"late-pcm")
        assert not await controller.release()

    asyncio.run(scenario())
    assert connection.sent == [
        ("assistant.interrupt", {"reason": "pilot_ptt"}),
        ("ptt.start", {}),
        ("audio", b"pcm"),
    ]


def test_reset_stops_capture_and_playback_without_completing_turn() -> None:
    connection = FakeConnection()
    capture = FakeCapture()
    playback = FakePlayback()
    controller = PttSessionController(  # type: ignore[arg-type]
        connection, capture, playback
    )

    async def scenario() -> None:
        assert await controller.press()
        await controller.reset()
        assert not controller.active

    asyncio.run(scenario())
    assert capture.events == ["capture.start", "capture.stop"]
    assert playback.events == ["playback.interrupt", "playback.interrupt"]
    assert [item[0] for item in connection.sent] == [
        "assistant.interrupt",
        "ptt.start",
        "audio",
    ]
