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
        self._lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self._active

    async def press(self) -> bool:
        async with self._lock:
            if self._active:
                return True
            if not self.connection.ready:
                self._notice("Copilot cloud unavailable")
                return False
            await self.playback.interrupt()
            self.connection.send_control("assistant.interrupt", {"reason": "pilot_ptt"})
            if not self.connection.send_control("ptt.start", {}):
                self._notice("Copilot cloud unavailable")
                return False
            generation = self.connection.session_generation

            def transmit(audio: bytes) -> None:
                if self.connection.session_generation == generation:
                    self.connection.send_audio(audio)

            try:
                await self.capture.start(transmit)
            except Exception:
                self.connection.send_control("ptt.end", {})
                raise
            self._active = True
            self._session_generation = generation
            self._notice("PTT active")
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
            self._notice("PTT released" if sent else "Copilot cloud unavailable")
            return sent

    def _notice(self, message: str) -> None:
        if self._on_notice is not None:
            self._on_notice(message)
