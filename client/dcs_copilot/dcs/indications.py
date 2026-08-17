"""Local, development-only transport for DCS ``list_indication()`` output."""

from __future__ import annotations

import secrets
import socket
import time
from dataclasses import dataclass
from typing import Iterator


PROTOCOL = "MARA_INDICATION"
PROTOCOL_VERSION = 1
DEFAULT_CONTROL_PORT = 7779
MAX_INDICATORS = 256
MAX_RANGE_SIZE = 64
MAX_ASSEMBLED_BYTES = 4 * 1024 * 1024


class IndicationProtocolError(ValueError):
    """Raised when a probe datagram is malformed or exceeds safety bounds."""


@dataclass(frozen=True, slots=True)
class RawIndicatorState:
    """One raw cockpit indicator observation with no semantic interpretation."""

    indicator_id: int
    raw: str
    observed_at: float
    received_at: float
    sequence: int
    error: str | None = None


@dataclass(slots=True)
class _PendingPacket:
    indicator_id: int
    observed_at: float
    status: str
    chunk_count: int
    chunks: dict[int, bytes]
    received_at: float
    size: int = 0


class IndicationPacketAssembler:
    """Reassemble bounded UDP chunks emitted by the Lua indication probe."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._pending: dict[int, _PendingPacket] = {}

    def feed(
        self,
        datagram: bytes,
        received_at: float | None = None,
    ) -> RawIndicatorState | None:
        header, separator, payload = datagram.partition(b"\n")
        if not separator:
            raise IndicationProtocolError("indication packet has no header separator")
        try:
            parts = header.decode("ascii").split()
        except UnicodeDecodeError as exc:
            raise IndicationProtocolError(
                "indication packet header is not ASCII"
            ) from exc
        if len(parts) != 10:
            raise IndicationProtocolError(
                "indication packet header has an invalid field count"
            )
        (
            protocol,
            version,
            token,
            sequence,
            indicator,
            chunk,
            count,
            observed,
            status,
            length,
        ) = parts
        if protocol != PROTOCOL or version != str(PROTOCOL_VERSION):
            raise IndicationProtocolError("unsupported indication protocol")
        if token != self.token:
            return None
        try:
            sequence_number = int(sequence)
            indicator_id = int(indicator)
            chunk_index = int(chunk)
            chunk_count = int(count)
            observed_at = float(observed)
            payload_length = int(length)
        except ValueError as exc:
            raise IndicationProtocolError(
                "indication packet has an invalid numeric field"
            ) from exc
        if not 0 <= indicator_id < MAX_INDICATORS:
            raise IndicationProtocolError("indicator ID is outside the supported range")
        if not 1 <= chunk_count <= 128 or not 0 <= chunk_index < chunk_count:
            raise IndicationProtocolError(
                "indication packet has invalid chunk metadata"
            )
        if status not in {"OK", "ERROR"}:
            raise IndicationProtocolError("indication packet has an invalid status")
        if payload_length != len(payload):
            raise IndicationProtocolError(
                "indication packet payload length does not match"
            )

        arrival = received_at if received_at is not None else time.time()
        pending = self._pending.get(sequence_number)
        if pending is None:
            pending = _PendingPacket(
                indicator_id,
                observed_at,
                status,
                chunk_count,
                {},
                arrival,
            )
            self._pending[sequence_number] = pending
        elif (
            pending.indicator_id != indicator_id
            or pending.chunk_count != chunk_count
            or pending.status != status
        ):
            del self._pending[sequence_number]
            raise IndicationProtocolError(
                "indication chunks have inconsistent metadata"
            )
        if chunk_index not in pending.chunks:
            pending.chunks[chunk_index] = payload
            pending.size += len(payload)
        if pending.size > MAX_ASSEMBLED_BYTES:
            del self._pending[sequence_number]
            raise IndicationProtocolError("indication output exceeds the size limit")
        if len(pending.chunks) != pending.chunk_count:
            self._discard_stale(arrival)
            return None

        complete = b"".join(pending.chunks[index] for index in range(chunk_count))
        del self._pending[sequence_number]
        decoded = complete.decode("utf-8", errors="replace")
        return RawIndicatorState(
            indicator_id=indicator_id,
            raw="" if status == "ERROR" else decoded,
            observed_at=observed_at,
            received_at=pending.received_at,
            sequence=sequence_number,
            error=decoded if status == "ERROR" else None,
        )

    def _discard_stale(self, now: float) -> None:
        for sequence, packet in tuple(self._pending.items()):
            if now - packet.received_at > 5.0:
                del self._pending[sequence]


class DcsIndicationReader:
    """Request raw indication snapshots from the loopback-only DCS Lua probe."""

    def __init__(
        self,
        *,
        control_port: int = DEFAULT_CONTROL_PORT,
        socket_factory: type[socket.socket] = socket.socket,
    ) -> None:
        if not 1 <= control_port <= 65535:
            raise ValueError("control port must be between 1 and 65535")
        self.control_port = control_port
        self._socket_factory = socket_factory

    def scan(
        self,
        first_id: int,
        last_id: int,
        *,
        timeout: float = 2.0,
    ) -> tuple[RawIndicatorState, ...]:
        _validate_range(first_id, last_id)
        token = secrets.token_hex(8)
        assembler = IndicationPacketAssembler(token)
        states: dict[int, RawIndicatorState] = {}
        deadline = time.monotonic() + max(0.0, timeout)
        with self._open_socket() as sock:
            request = self._request("SCAN", token, first_id, last_id)
            next_request = 0.0
            while len(states) < last_id - first_id + 1:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                now = time.monotonic()
                if now >= next_request:
                    sock.sendto(request, ("127.0.0.1", self.control_port))
                    next_request = now + 0.5
                sock.settimeout(min(remaining, max(0.01, next_request - now)))
                try:
                    datagram, peer = sock.recvfrom(65535)
                except TimeoutError:
                    continue
                if peer[0] != "127.0.0.1":
                    continue
                state = assembler.feed(datagram)
                if state is not None:
                    states[state.indicator_id] = state
        return tuple(states[indicator] for indicator in sorted(states))

    def watch(
        self,
        first_id: int,
        last_id: int,
        *,
        poll_hz: float = 10.0,
    ) -> Iterator[RawIndicatorState]:
        _validate_range(first_id, last_id)
        if not 0.1 <= poll_hz <= 10.0:
            raise ValueError("poll rate must be between 0.1 and 10 Hz")
        token = secrets.token_hex(8)
        assembler = IndicationPacketAssembler(token)
        interval = 1.0 / poll_hz
        request = self._request("WATCH", token, first_id, last_id, interval)
        with self._open_socket() as sock:
            next_heartbeat = 0.0
            try:
                while True:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        sock.sendto(request, ("127.0.0.1", self.control_port))
                        next_heartbeat = now + 2.0
                    sock.settimeout(max(0.05, next_heartbeat - now))
                    try:
                        datagram, peer = sock.recvfrom(65535)
                    except TimeoutError:
                        continue
                    if peer[0] != "127.0.0.1":
                        continue
                    state = assembler.feed(datagram)
                    if state is not None:
                        yield state
            finally:
                stop = f"{PROTOCOL}/{PROTOCOL_VERSION} STOP {token}".encode("ascii")
                try:
                    sock.sendto(stop, ("127.0.0.1", self.control_port))
                except OSError:
                    pass

    def _open_socket(self) -> socket.socket:
        sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        return sock

    @staticmethod
    def _request(
        command: str,
        token: str,
        first_id: int,
        last_id: int,
        interval: float | None = None,
    ) -> bytes:
        fields = [
            f"{PROTOCOL}/{PROTOCOL_VERSION}",
            command,
            token,
            str(first_id),
            str(last_id),
        ]
        if interval is not None:
            fields.append(f"{interval:.6f}")
        return " ".join(fields).encode("ascii")


def _validate_range(first_id: int, last_id: int) -> None:
    if not 0 <= first_id < MAX_INDICATORS:
        raise ValueError(
            f"first indicator ID must be between 0 and {MAX_INDICATORS - 1}"
        )
    if not first_id <= last_id < MAX_INDICATORS:
        raise ValueError(
            f"last indicator ID must be between first ID and {MAX_INDICATORS - 1}"
        )
    if last_id - first_id + 1 > MAX_RANGE_SIZE:
        raise ValueError(
            f"indicator range cannot contain more than {MAX_RANGE_SIZE} IDs"
        )
