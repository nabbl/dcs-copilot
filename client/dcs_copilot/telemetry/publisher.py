"""Catalog, snapshot, and coalesced delta publishing for protocol v2."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar
from uuid import uuid4

from dcs_copilot_protocol import (
    CatalogEntry,
    ControlIdentity,
    ControlMessage,
    DecodedValue,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetrySnapshot,
)

from dcs_copilot.dcs.bios_client import ControlChange, DcsBiosClient
from dcs_copilot.dcs.bios_registry import ControlDefinition

ControlSender = Callable[[ControlMessage], bool]
T = TypeVar("T")


class TelemetryPublisher:
    """Keeps DCS ingestion independent from bounded network transmission."""

    def __init__(
        self,
        client: DcsBiosClient,
        send_control: ControlSender,
        *,
        flush_hz: float = 15.0,
        max_pending_controls: int = 8_192,
        max_switch_transitions: int = 8,
    ) -> None:
        if not 10 <= flush_hz <= 20:
            raise ValueError("telemetry flush rate must be between 10 and 20 Hz")
        if max_pending_controls <= 0 or max_switch_transitions <= 0:
            raise ValueError("telemetry queue bounds must be positive")
        self.client = client
        self._send_control = send_control
        self.flush_interval = 1.0 / flush_hz
        self.max_pending_controls = max_pending_controls
        self.max_switch_transitions = max_switch_transitions
        self._session_active = False
        self._epoch: str | None = None
        self._aircraft: str | None = None
        self._next_sequence = 0
        self._initial: deque[ControlMessage] = deque()
        self._pending: dict[ControlIdentity, deque[DecodedValue]] = {}
        self._catalog: dict[ControlIdentity, CatalogEntry] = {}
        self._active_modules: set[str] = set()
        self.dropped_controls = 0
        self.coalesced_values = 0
        client.add_aircraft_callback(self._aircraft_changed)
        client.add_change_callback(self._control_changed)
        client.add_connection_callback(self._dcs_connection_changed)

    @property
    def epoch(self) -> str | None:
        return self._epoch

    @property
    def pending_count(self) -> int:
        return sum(len(values) for values in self._pending.values()) + len(
            self._initial
        )

    def set_session_active(self, active: bool) -> None:
        self._session_active = active
        if not active:
            self._reset()
            return
        self._begin_epoch(self.client.current_aircraft)

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.flush()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.flush_interval)
            except TimeoutError:
                pass

    def flush(self) -> None:
        if not self._session_active or self._epoch is None:
            return
        while self._initial:
            if not self._send_control(self._initial[0]):
                return
            self._initial.popleft()
        if not self._pending:
            return
        values: list[DecodedValue] = []
        identities: list[ControlIdentity] = []
        for identity, queued in self._pending.items():
            if not queued:
                continue
            identities.append(identity)
            values.append(queued[0])
            if len(values) == 1_024:
                break
        if not values:
            return
        message = TelemetryDelta(
            epoch=self._epoch,
            sequence=self._next_sequence,
            aircraft=self._aircraft or "",
            chunk_index=0,
            chunk_count=1,
            values=tuple(values),
        ).to_control()
        if not self._send_control(message):
            return
        self._next_sequence += 1
        for identity in identities:
            queued = self._pending[identity]
            queued.popleft()
            if not queued:
                del self._pending[identity]

    def _aircraft_changed(self, aircraft: str | None) -> None:
        if self._session_active:
            self._begin_epoch(aircraft)

    def _dcs_connection_changed(self, connected: bool) -> None:
        if not connected:
            self._reset()

    def _begin_epoch(self, aircraft: str | None) -> None:
        self._reset()
        if not self._session_active or aircraft is None:
            return
        definitions = self.client.active_definitions()
        self._epoch = str(uuid4())
        self._aircraft = aircraft
        self._catalog = {
            self._identity(definition): self._catalog_entry(definition)
            for definition in definitions
        }
        self._active_modules = {definition.module for definition in definitions}
        catalog_entries = tuple(self._catalog.values())
        catalog_chunks = _chunks(catalog_entries, 256)
        if not catalog_chunks:
            catalog_chunks = ((),)
        for index, entries in enumerate(catalog_chunks):
            self._initial.append(
                TelemetryCatalog(
                    epoch=self._epoch,
                    sequence=self._take_sequence(),
                    aircraft=aircraft,
                    chunk_index=index,
                    chunk_count=len(catalog_chunks),
                    entries=entries,
                ).to_control()
            )

        snapshot_values = tuple(
            self._decoded_value(change) for change in self.client.decoded_snapshot()
        )
        snapshot_chunks = _chunks(snapshot_values, 1_024)
        if not snapshot_chunks:
            snapshot_chunks = ((),)
        for index, values in enumerate(snapshot_chunks):
            self._initial.append(
                TelemetrySnapshot(
                    epoch=self._epoch,
                    sequence=self._take_sequence(),
                    aircraft=aircraft,
                    chunk_index=index,
                    chunk_count=len(snapshot_chunks),
                    values=values,
                ).to_control()
            )

    def _control_changed(self, change: ControlChange) -> None:
        if (
            not self._session_active
            or self._epoch is None
            or change.control.module not in self._active_modules
        ):
            return
        value = self._decoded_value(change)
        identity = value.identity
        queued = self._pending.get(identity)
        if queued is None:
            if len(self._pending) >= self.max_pending_controls:
                self.dropped_controls += 1
                return
            queued = deque()
            self._pending[identity] = queued
        catalog = self._catalog.get(identity)
        preserve_transitions = (
            catalog is not None
            and catalog.identity.output_type == "integer"
            and catalog.integer_max == 1
        )
        if queued and queued[-1].value == value.value:
            queued[-1] = value
            self.coalesced_values += 1
        elif preserve_transitions:
            if len(queued) >= self.max_switch_transitions:
                queued[-1] = value
                self.coalesced_values += 1
            else:
                queued.append(value)
        elif queued:
            queued[-1] = value
            self.coalesced_values += 1
        else:
            queued.append(value)

    def _take_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence

    def _reset(self) -> None:
        self._epoch = None
        self._aircraft = None
        self._next_sequence = 0
        self._initial.clear()
        self._pending.clear()
        self._catalog.clear()
        self._active_modules.clear()

    @staticmethod
    def _identity(definition: ControlDefinition) -> ControlIdentity:
        return ControlIdentity(
            module=definition.module,
            identifier=definition.identifier,
            output_type=definition.output_type,
            output_index=definition.output_index,
        )

    @classmethod
    def _catalog_entry(cls, definition: ControlDefinition) -> CatalogEntry:
        return CatalogEntry(
            identity=cls._identity(definition),
            integer_max=definition.max_value,
            string_length=definition.string_length,
            description=definition.description[:256] or definition.identifier,
        )

    @classmethod
    def _decoded_value(cls, change: ControlChange) -> DecodedValue:
        return DecodedValue(
            identity=cls._identity(change.control),
            value=change.value,
            available=True,
            observed_at_ms=max(0, round(change.observed_at * 1_000)),
        )


def _chunks(values: tuple[T, ...], size: int) -> tuple[tuple[T, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))
