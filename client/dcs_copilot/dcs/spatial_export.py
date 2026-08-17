"""Loopback-only receiver for normalized, permission-gated DCS spatial export."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable

from dcs_copilot_protocol import (
    CoachCapabilitiesPayload,
    CoachTelemetry,
    ControlMessage,
    ProtocolError,
)

MAX_DATAGRAM_BYTES = 64 * 1024


def parse_spatial_datagram(
    payload: bytes,
    *,
    cockpit_state: bool | None = None,
) -> CoachTelemetry:
    if len(payload) > MAX_DATAGRAM_BYTES:
        raise ProtocolError("DCS spatial datagram exceeds 64 KiB")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid DCS spatial JSON") from exc
    if not isinstance(document, dict):
        raise ProtocolError("DCS spatial datagram must be an object")
    message = CoachTelemetry.from_control(ControlMessage("coach.telemetry", document))
    if cockpit_state is None:
        return message
    capabilities = CoachCapabilitiesPayload(
        ownship_export=message.capabilities.ownship_export,
        world_object_export=message.capabilities.world_object_export,
        sensor_export=message.capabilities.sensor_export,
        cockpit_state=cockpit_state,
    )
    return CoachTelemetry(
        sequence=message.sequence,
        observed_at_ms=message.observed_at_ms,
        capabilities=capabilities,
        ownship=message.ownship,
        references=message.references,
    )


class DcsSpatialClient(asyncio.DatagramProtocol):
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 7780,
        on_observation: Callable[[CoachTelemetry], None] | None = None,
        cockpit_state_provider: Callable[[], bool] | None = None,
        stale_timeout: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("DCS spatial export must bind to loopback")
        if not 1 <= port <= 65535:
            raise ValueError("DCS spatial port must be between 1 and 65535")
        if stale_timeout <= 0:
            raise ValueError("DCS spatial stale timeout must be positive")
        self.host = host
        self.port = port
        self._on_observation = on_observation
        self._cockpit_state_provider = cockpit_state_provider
        self._clock = clock
        self.stale_timeout = stale_timeout
        self.transport: asyncio.DatagramTransport | None = None
        self.last_observation: CoachTelemetry | None = None
        self.last_received_at: float | None = None
        self.parser_errors = 0
        self._failed_closed = False

    @property
    def frame_age(self) -> float | None:
        if self.last_received_at is None:
            return None
        return max(0.0, self._clock() - self.last_received_at)

    @property
    def connected(self) -> bool:
        age = self.frame_age
        return age is not None and age <= self.stale_timeout

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] not in {"127.0.0.1", "::1"}:
            return
        try:
            observation = parse_spatial_datagram(
                data,
                cockpit_state=(
                    self._cockpit_state_provider()
                    if self._cockpit_state_provider is not None
                    else None
                ),
            )
        except (ProtocolError, ValueError):
            self.parser_errors += 1
            return
        self.last_observation = observation
        self.last_received_at = self._clock()
        self._failed_closed = False
        if self._on_observation is not None:
            self._on_observation(observation)

    def error_received(self, _exc: Exception) -> None:
        self.parser_errors += 1

    async def run(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self.host, self.port),
        )
        try:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.5)
                except TimeoutError:
                    self._fail_closed_if_stale()
        finally:
            transport.close()
            self.transport = None

    def _fail_closed_if_stale(self) -> None:
        age = self.frame_age
        if age is None or age <= self.stale_timeout or self._failed_closed:
            return
        previous_sequence = (
            self.last_observation.sequence if self.last_observation else 0
        )
        unavailable = CoachTelemetry(
            sequence=previous_sequence + 1,
            observed_at_ms=max(0, round(self._clock() * 1000)),
            capabilities=CoachCapabilitiesPayload(
                ownship_export=False,
                world_object_export=False,
                sensor_export=False,
                cockpit_state=(
                    self._cockpit_state_provider()
                    if self._cockpit_state_provider is not None
                    else False
                ),
            ),
        )
        self.last_observation = unavailable
        self._failed_closed = True
        if self._on_observation is not None:
            self._on_observation(unavailable)
