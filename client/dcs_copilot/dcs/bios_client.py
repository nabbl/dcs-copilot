"""Async multicast client for the read-only DCS-BIOS export stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

from .bios_protocol import DcsBiosProtocolParser, FrameComplete
from .bios_registry import ControlDefinition, DcsBiosControlRegistry
from .bios_state import DcsBiosState, StateWrite

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ControlChange:
    control: ControlDefinition
    value: int | str


class DcsBiosClient:
    def __init__(
        self,
        *,
        multicast_group: str = "239.255.50.10",
        port: int = 5010,
        interface: str = "127.0.0.1",
        stale_timeout: float = 2.0,
        registry: DcsBiosControlRegistry | None = None,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        self.multicast_group = multicast_group
        self.port = port
        self.interface = interface
        self.stale_timeout = stale_timeout
        self.registry = registry
        self._socket_factory = socket_factory
        self.state = DcsBiosState()
        self.parser = DcsBiosProtocolParser(
            self.state,
            on_write=self._on_write,
            on_frame_complete=self._on_frame_complete,
        )
        self.socket: socket.socket | None = None
        self.latest_frame_at: float | None = None
        self.current_aircraft: str | None = None
        self._connected = False
        self._pending_definitions: set[ControlDefinition] = set()
        self._decoded_values: dict[ControlDefinition, int | str] = {}
        self._frame_callbacks: list[Callable[[FrameComplete], None]] = []
        self._change_callbacks: list[Callable[[ControlChange], None]] = []
        self._connection_callbacks: list[Callable[[bool], None]] = []

    @property
    def connected(self) -> bool:
        self._expire_if_stale()
        return self._connected

    @property
    def frame_age(self) -> float | None:
        if self.latest_frame_at is None:
            return None
        return max(0.0, time.monotonic() - self.latest_frame_at)

    def add_frame_callback(self, callback: Callable[[FrameComplete], None]) -> None:
        self._frame_callbacks.append(callback)

    def add_change_callback(self, callback: Callable[[ControlChange], None]) -> None:
        self._change_callbacks.append(callback)

    def add_connection_callback(self, callback: Callable[[bool], None]) -> None:
        self._connection_callbacks.append(callback)

    def open(self) -> None:
        if self.socket is not None:
            return
        sock = self._socket_factory(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
        )
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
            membership = socket.inet_aton(self.multicast_group) + socket.inet_aton(
                self.interface
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            sock.setblocking(False)
        except Exception:
            sock.close()
            raise
        self.socket = sock
        LOG.info("DCS-BIOS socket opened", extra={"event": "dcs_socket_opened"})

    def close(self) -> None:
        had_socket = self.socket is not None
        if self.socket is not None:
            with contextlib.suppress(OSError):
                membership = socket.inet_aton(self.multicast_group) + socket.inet_aton(
                    self.interface
                )
                self.socket.setsockopt(
                    socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, membership
                )
            self.socket.close()
            self.socket = None
        self.state.clear_availability()
        self.current_aircraft = None
        was_connected = self._connected
        self._connected = False
        self._pending_definitions.clear()
        self._decoded_values.clear()
        if had_socket:
            LOG.info("DCS-BIOS disconnected", extra={"event": "dcs_disconnected"})
        if was_connected:
            self._emit_connection(False)

    async def receive_once(self, timeout: float | None = None) -> int:
        self.open()
        assert self.socket is not None
        loop = asyncio.get_running_loop()
        receive = loop.sock_recvfrom(self.socket, 65535)
        data, _peer = (
            await asyncio.wait_for(receive, timeout) if timeout else await receive
        )
        self.parser.feed(data)
        return len(data)

    async def listen_for(self, duration: float) -> None:
        deadline = time.monotonic() + max(0.0, duration)
        self.open()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                await self.receive_once(timeout=remaining)
            except TimeoutError:
                break

    async def run(self, stop: asyncio.Event) -> None:
        self.open()
        try:
            while not stop.is_set():
                try:
                    await self.receive_once(timeout=0.5)
                except TimeoutError:
                    self._expire_if_stale()
                    continue
        finally:
            self.close()

    def _on_write(self, write: StateWrite) -> None:
        if self.registry is not None and write.changed:
            self._pending_definitions.update(
                self.registry.definitions_for_range(write.address, len(write.data))
            )

    def _on_frame_complete(self, frame: FrameComplete) -> None:
        was_connected = self._connected
        self.latest_frame_at = time.monotonic()
        self._connected = True
        if not was_connected:
            LOG.info("DCS connected", extra={"event": "dcs_connected"})
            self._emit_connection(True)
        self._update_aircraft(frame)
        self._emit_control_changes()
        for callback in tuple(self._frame_callbacks):
            callback(frame)

    def _expire_if_stale(self) -> None:
        if not self._connected:
            return
        age = self.frame_age
        if age is not None and age > self.stale_timeout:
            self._connected = False
            self.state.clear_availability()
            self.current_aircraft = None
            self._pending_definitions.clear()
            self._decoded_values.clear()
            LOG.info("DCS-BIOS timed out", extra={"event": "dcs_disconnected"})
            self._emit_connection(False)

    def _emit_connection(self, connected: bool) -> None:
        for callback in tuple(self._connection_callbacks):
            callback(connected)

    def _update_aircraft(self, frame: FrameComplete) -> None:
        if self.registry is None:
            return
        definition = self.registry.resolve(
            "_ACFT_NAME", module="MetadataStart", output_type="string"
        )
        if definition is None:
            return
        decoded = self.registry.decode(definition, self.state)
        aircraft = (
            decoded
            if isinstance(decoded, str) and decoded and decoded != "NONE"
            else None
        )
        if aircraft != self.current_aircraft:
            # Module address ranges can retain bytes from a previously active
            # cockpit. Keep only values actually exported in the new aircraft's
            # first frame so unavailable controls cannot inherit stale data.
            self.state.clear_availability()
            for write in frame.writes:
                self.state.apply_write(
                    write.address, write.data, received_at=write.received_at
                )
            self._decoded_values.clear()
            self.current_aircraft = aircraft
            LOG.info(
                "aircraft changed",
                extra={"event": "aircraft_changed", "aircraft": aircraft or "NONE"},
            )

    def _emit_control_changes(self) -> None:
        if self.registry is None:
            self._pending_definitions.clear()
            return
        active_modules = (
            set(self.registry.modules_for_aircraft(self.current_aircraft))
            if self.current_aircraft
            else set()
        )
        for definition in sorted(
            self._pending_definitions,
            key=lambda item: (item.module, item.identifier, item.output_type),
        ):
            if (
                definition.module
                not in {"MetadataStart", "MetadataEnd"} | active_modules
            ):
                continue
            value = self.registry.decode(definition, self.state)
            if value is None or self._decoded_values.get(definition) == value:
                continue
            self._decoded_values[definition] = value
            change = ControlChange(definition, value)
            for callback in tuple(self._change_callbacks):
                callback(change)
        self._pending_definitions.clear()
