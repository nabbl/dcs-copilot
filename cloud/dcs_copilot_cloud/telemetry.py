"""Strict protocol-v2 telemetry assembly for one realtime connection."""

from __future__ import annotations

from dataclasses import dataclass

from dcs_copilot_protocol import (
    CatalogEntry,
    ControlIdentity,
    ControlMessage,
    DecodedValue,
    ProtocolError,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetrySnapshot,
)


class TelemetryIngressError(ProtocolError):
    pass


MAX_SESSION_CONTROLS = 4_096


@dataclass(frozen=True, slots=True)
class TelemetryBatch:
    kind: str
    epoch: str
    aircraft: str
    catalog: tuple[CatalogEntry, ...] = ()
    values: tuple[DecodedValue, ...] = ()


class TelemetryIngress:
    """Accepts only a contiguous catalog, snapshot, then delta stream."""

    def __init__(self) -> None:
        self.epoch: str | None = None
        self.aircraft: str | None = None
        self.last_sequence: int | None = None
        self.ready = False
        self._catalog_chunk_count: int | None = None
        self._catalog_chunks = 0
        self._catalog: dict[ControlIdentity, CatalogEntry] = {}
        self._snapshot_chunk_count: int | None = None
        self._snapshot_chunks = 0
        self._snapshot: dict[ControlIdentity, DecodedValue] = {}

    def accept(self, message: ControlMessage) -> TelemetryBatch | None:
        if message.type == "telemetry.catalog":
            return self._accept_catalog(TelemetryCatalog.from_control(message))
        if message.type == "telemetry.snapshot":
            return self._accept_snapshot(TelemetrySnapshot.from_control(message))
        if message.type == "telemetry.delta":
            return self._accept_delta(TelemetryDelta.from_control(message))
        raise TelemetryIngressError("expected a telemetry message")

    def disconnect(self) -> None:
        self._clear()

    def _accept_catalog(self, message: TelemetryCatalog) -> TelemetryBatch | None:
        new_epoch = message.epoch != self.epoch
        if new_epoch:
            if message.sequence != 0 or message.chunk_index != 0:
                raise TelemetryIngressError(
                    "a new telemetry epoch must start with catalog sequence 0 chunk 0"
                )
            self._start_epoch(message.epoch, message.aircraft)
        else:
            self._require_context(message.epoch, message.aircraft)
            self._require_sequence(message.sequence)
            if self.ready or self._snapshot_chunk_count is not None:
                raise TelemetryIngressError(
                    "catalog messages are not accepted after snapshot assembly starts"
                )
        if message.chunk_index != self._catalog_chunks:
            raise TelemetryIngressError("catalog chunks must be contiguous and ordered")
        if self._catalog_chunk_count is None:
            self._catalog_chunk_count = message.chunk_count
        elif message.chunk_count != self._catalog_chunk_count:
            raise TelemetryIngressError("catalog chunk_count changed within an epoch")
        for entry in message.entries:
            if entry.identity in self._catalog:
                raise TelemetryIngressError("catalog identity was repeated across chunks")
            if len(self._catalog) >= MAX_SESSION_CONTROLS:
                raise TelemetryIngressError("telemetry catalog exceeds session bounds")
            self._catalog[entry.identity] = entry
        self._catalog_chunks += 1
        self.last_sequence = message.sequence
        if new_epoch:
            return TelemetryBatch("reset", message.epoch, message.aircraft)
        return None

    def _accept_snapshot(
        self, message: TelemetrySnapshot
    ) -> TelemetryBatch | None:
        self._require_context(message.epoch, message.aircraft)
        self._require_sequence(message.sequence)
        if not self._catalog_complete:
            raise TelemetryIngressError(
                "snapshot is not accepted before the complete catalog"
            )
        if self.ready:
            raise TelemetryIngressError("snapshot is already complete for this epoch")
        if message.chunk_index != self._snapshot_chunks:
            raise TelemetryIngressError("snapshot chunks must be contiguous and ordered")
        if self._snapshot_chunk_count is None:
            self._snapshot_chunk_count = message.chunk_count
        elif message.chunk_count != self._snapshot_chunk_count:
            raise TelemetryIngressError("snapshot chunk_count changed within an epoch")
        for value in message.values:
            self._validate_value(value)
            if value.identity in self._snapshot:
                raise TelemetryIngressError("snapshot identity was repeated across chunks")
            if len(self._snapshot) >= MAX_SESSION_CONTROLS:
                raise TelemetryIngressError("telemetry snapshot exceeds session bounds")
            self._snapshot[value.identity] = value
        self._snapshot_chunks += 1
        self.last_sequence = message.sequence
        if self._snapshot_chunks != self._snapshot_chunk_count:
            return None
        self.ready = True
        return TelemetryBatch(
            "snapshot",
            message.epoch,
            message.aircraft,
            tuple(self._catalog.values()),
            tuple(self._snapshot.values()),
        )

    def _accept_delta(self, message: TelemetryDelta) -> TelemetryBatch:
        self._require_context(message.epoch, message.aircraft)
        self._require_sequence(message.sequence)
        if not self.ready:
            raise TelemetryIngressError(
                "delta is not accepted before the complete initial snapshot"
            )
        if message.chunk_index != 0 or message.chunk_count != 1:
            raise TelemetryIngressError("telemetry deltas cannot be chunked")
        for value in message.values:
            self._validate_value(value)
        self.last_sequence = message.sequence
        return TelemetryBatch(
            "delta",
            message.epoch,
            message.aircraft,
            values=tuple(message.values),
        )

    @property
    def _catalog_complete(self) -> bool:
        return (
            self._catalog_chunk_count is not None
            and self._catalog_chunks == self._catalog_chunk_count
        )

    def _validate_value(self, value: DecodedValue) -> None:
        entry = self._catalog.get(value.identity)
        if entry is None:
            raise TelemetryIngressError("telemetry value is not present in the catalog")
        if not value.available:
            return
        if value.identity.output_type == "integer":
            if not isinstance(value.value, int) or entry.integer_max is None:
                raise TelemetryIngressError(
                    "integer telemetry does not match its catalog entry"
                )
            if value.value < 0 or value.value > entry.integer_max:
                raise TelemetryIngressError(
                    "integer telemetry value exceeds its catalog range"
                )
        else:
            if not isinstance(value.value, str) or entry.string_length is None:
                raise TelemetryIngressError(
                    "string telemetry does not match its catalog entry"
                )
            if len(value.value) > entry.string_length:
                raise TelemetryIngressError(
                    "string telemetry value exceeds its catalog length"
                )

    def _require_context(self, epoch: str, aircraft: str) -> None:
        if self.epoch is None:
            raise TelemetryIngressError("telemetry epoch has not started")
        if epoch != self.epoch:
            raise TelemetryIngressError("telemetry message has the wrong epoch")
        if aircraft != self.aircraft:
            raise TelemetryIngressError("telemetry message has the wrong aircraft")

    def _require_sequence(self, sequence: int) -> None:
        if self.last_sequence is None or sequence != self.last_sequence + 1:
            raise TelemetryIngressError(
                "telemetry sequence is stale, duplicated, or out of order"
            )

    def _start_epoch(self, epoch: str, aircraft: str) -> None:
        self._clear()
        self.epoch = epoch
        self.aircraft = aircraft

    def _clear(self) -> None:
        self.epoch = None
        self.aircraft = None
        self.last_sequence = None
        self.ready = False
        self._catalog_chunk_count = None
        self._catalog_chunks = 0
        self._catalog.clear()
        self._snapshot_chunk_count = None
        self._snapshot_chunks = 0
        self._snapshot.clear()
