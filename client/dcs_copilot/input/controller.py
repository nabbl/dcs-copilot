"""PTT lifecycle: interrupt, capture, stream, and authoritative turn end."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from dcs_copilot.network.connection import CloudSessionConnection


class AudioCapture(Protocol):
    async def start(self, on_audio: Callable[[bytes], None]) -> None: ...

    async def stop(self) -> None: ...


class AudioPlayback(Protocol):
    async def interrupt(self) -> None: ...


class PttSessionController:
    def __init__(
        self,
        connection: CloudSessionConnection,
        capture: AudioCapture,
        playback: AudioPlayback,
        *,
        on_notice: Callable[[str], None] | None = None,
    ) -> None:
        self.connection = connection
        self.capture = capture
        self.playback = playback
        self._on_notice = on_notice
        self._active = False
        self._session_generation: int | None = None
        self._audio_chunks = 0
        self._audio_bytes = 0
        self._dropped_audio_chunks = 0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self._active

    async def press(self) -> bool:
        async with self._lock:
            if self._active:
                return True
            if not self.connection.ready:
                self._notice("Error: cloud unavailable; PTT not started")
                return False
            await self.playback.interrupt()
            self.connection.send_control("assistant.interrupt", {"reason": "pilot_ptt"})
            if not self.connection.send_control("ptt.start", {}):
                self._notice("Error: PTT start was not queued")
                return False
            generation = self.connection.session_generation
            self._audio_chunks = 0
            self._audio_bytes = 0
            self._dropped_audio_chunks = 0

            def transmit(audio: bytes) -> None:
                if self.connection.session_generation == generation:
                    if self.connection.send_audio(audio):
                        self._audio_chunks += 1
                        self._audio_bytes += len(audio)
                    else:
                        self._dropped_audio_chunks += 1

            try:
                await self.capture.start(transmit)
            except Exception:
                self.connection.send_control("ptt.end", {})
                raise
            self._active = True
            self._session_generation = generation
            self._notice("PTT: active")
            return True

    async def release(self) -> bool:
        async with self._lock:
            if not self._active:
                return False
            await self.capture.stop()
            sent = (
                self.connection.send_control("ptt.end", {})
                if self.connection.session_generation == self._session_generation
                else False
            )
            self._active = False
            self._session_generation = None
            if sent:
                self._notice(
                    "PTT: released "
                    f"audio_chunks={self._audio_chunks} "
                    f"audio_bytes={self._audio_bytes} "
                    f"dropped={self._dropped_audio_chunks}"
                )
            else:
                self._notice("Error: PTT end was not queued")
            return sent

    async def reset(self) -> None:
        async with self._lock:
            if self._active:
                await self.capture.stop()
            self._active = False
            self._session_generation = None
            await self.playback.interrupt()

    def _notice(self, message: str) -> None:
        if self._on_notice is not None:
            self._on_notice(message)
