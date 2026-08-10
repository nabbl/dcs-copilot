"""Incremental parser for the DCS-BIOS binary export protocol."""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass

from .bios_state import ADDRESS_SPACE_SIZE, DcsBiosState, StateWrite

SYNC_BYTE = 0x55
SYNC_LENGTH = 4


class _ParserState(enum.Enum):
    WAIT_FOR_SYNC = enum.auto()
    ADDRESS_LOW = enum.auto()
    ADDRESS_HIGH = enum.auto()
    COUNT_LOW = enum.auto()
    COUNT_HIGH = enum.auto()
    DATA = enum.auto()


@dataclass(frozen=True, slots=True)
class FrameComplete:
    number: int
    writes: tuple[StateWrite, ...]


class DcsBiosProtocolParser:
    """Consume arbitrary chunks and update a :class:`DcsBiosState`.

    Protocol writes are buffered until their complete payload arrives, so a
    truncated or corrupt write can never partially mutate the address space.
    """

    def __init__(
        self,
        state: DcsBiosState | None = None,
        *,
        on_write: Callable[[StateWrite], None] | None = None,
        on_frame_complete: Callable[[FrameComplete], None] | None = None,
    ) -> None:
        self.bios_state = state or DcsBiosState()
        self.on_write = on_write
        self.on_frame_complete = on_frame_complete
        self.error_count = 0
        self.frame_count = 0
        self._state = _ParserState.WAIT_FOR_SYNC
        self._sync_run = 0
        self._address = 0
        self._count = 0
        self._payload = bytearray()
        self._frame_started = False
        self._frame_writes: list[StateWrite] = []

    @property
    def synchronized(self) -> bool:
        return self._state is not _ParserState.WAIT_FOR_SYNC

    def feed(self, data: bytes | bytearray | memoryview) -> list[FrameComplete]:
        completed: list[FrameComplete] = []
        for value in data:
            if value == SYNC_BYTE:
                self._sync_run += 1
                if self._sync_run == SYNC_LENGTH:
                    frame = self._handle_sync()
                    if frame is not None:
                        completed.append(frame)
                continue
            while self._sync_run:
                self._consume(SYNC_BYTE)
                self._sync_run -= 1
            self._consume(value)
        return completed

    def _handle_sync(self) -> FrameComplete | None:
        frame: FrameComplete | None = None
        frame_was_complete = self._state is _ParserState.ADDRESS_LOW
        if self._frame_started and not frame_was_complete:
            self.error_count += 1
            self._frame_writes.clear()
        elif self._frame_started:
            self.frame_count += 1
            frame = FrameComplete(self.frame_count, tuple(self._frame_writes))
            if self.on_frame_complete:
                self.on_frame_complete(frame)
        self._frame_started = True
        self._frame_writes.clear()
        self._payload.clear()
        self._state = _ParserState.ADDRESS_LOW
        self._sync_run = 0
        return frame

    def _consume(self, value: int) -> None:
        if self._state is _ParserState.WAIT_FOR_SYNC:
            return
        if self._state is _ParserState.ADDRESS_LOW:
            self._address = value
            self._state = _ParserState.ADDRESS_HIGH
            return
        if self._state is _ParserState.ADDRESS_HIGH:
            self._address |= value << 8
            if self._address == 0x5555:
                self._malformed()
            else:
                self._state = _ParserState.COUNT_LOW
            return
        if self._state is _ParserState.COUNT_LOW:
            self._count = value
            self._state = _ParserState.COUNT_HIGH
            return
        if self._state is _ParserState.COUNT_HIGH:
            self._count |= value << 8
            if (
                self._count == 0
                or self._count % 2 != 0
                or self._address + self._count > ADDRESS_SPACE_SIZE
            ):
                self._malformed()
            else:
                self._payload.clear()
                self._state = _ParserState.DATA
            return
        if self._state is _ParserState.DATA:
            self._payload.append(value)
            if len(self._payload) == self._count:
                write = self.bios_state.apply_write(self._address, bytes(self._payload))
                self._frame_writes.append(write)
                if self.on_write:
                    self.on_write(write)
                self._payload.clear()
                self._state = _ParserState.ADDRESS_LOW

    def _malformed(self) -> None:
        self.error_count += 1
        self._payload.clear()
        self._frame_writes.clear()
        self._frame_started = False
        self._state = _ParserState.WAIT_FOR_SYNC
