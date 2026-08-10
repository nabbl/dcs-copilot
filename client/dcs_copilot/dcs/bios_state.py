"""In-memory representation of the DCS-BIOS address space."""

from __future__ import annotations

import time
from array import array
from dataclasses import dataclass

ADDRESS_SPACE_SIZE = 1 << 16


@dataclass(frozen=True, slots=True)
class StateWrite:
    address: int
    data: bytes
    changed: bool
    received_at: float


class DcsBiosState:
    """A 64 KiB byte buffer updated atomically per protocol write."""

    def __init__(self) -> None:
        self._buffer = bytearray(ADDRESS_SPACE_SIZE)
        self._available = bytearray(ADDRESS_SPACE_SIZE)
        self._updated_at = array("d", [0.0]) * ADDRESS_SPACE_SIZE
        self.latest_write_at: float | None = None

    def apply_write(
        self, address: int, data: bytes, *, received_at: float | None = None
    ) -> StateWrite:
        end = address + len(data)
        if address < 0 or end > ADDRESS_SPACE_SIZE:
            raise ValueError("write falls outside the DCS-BIOS address space")
        timestamp = time.monotonic() if received_at is None else received_at
        changed = self._buffer[address:end] != data or not all(
            self._available[address:end]
        )
        self._buffer[address:end] = data
        self._available[address:end] = b"\x01" * len(data)
        self._updated_at[address:end] = array("d", [timestamp]) * len(data)
        self.latest_write_at = timestamp
        return StateWrite(address, bytes(data), changed, timestamp)

    def read(self, address: int, length: int) -> bytes | None:
        end = address + length
        if address < 0 or length < 0 or end > ADDRESS_SPACE_SIZE:
            raise ValueError("read falls outside the DCS-BIOS address space")
        if length and not all(self._available[address:end]):
            return None
        return bytes(self._buffer[address:end])

    def clear_availability(self) -> None:
        self._available[:] = b"\x00" * ADDRESS_SPACE_SIZE

    def updated_at(self, address: int, length: int) -> float | None:
        end = address + length
        if address < 0 or length < 0 or end > ADDRESS_SPACE_SIZE:
            raise ValueError("timestamp range falls outside the DCS-BIOS address space")
        if not length or not all(self._available[address:end]):
            return None
        timestamps = self._updated_at[address:end]
        return min(timestamps) if timestamps else None

    @property
    def buffer(self) -> bytes:
        return bytes(self._buffer)
