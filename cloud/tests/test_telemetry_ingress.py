from __future__ import annotations

from uuid import uuid4

import pytest
from dcs_copilot_cloud.telemetry import TelemetryIngress, TelemetryIngressError
from dcs_copilot_protocol import (
    CatalogEntry,
    ControlIdentity,
    DecodedValue,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetrySnapshot,
)


IDENTITY = ControlIdentity("FA-18C_hornet", "BATTERY_SW", "integer", 0)
ENTRY = CatalogEntry(IDENTITY, "Battery switch", integer_max=2)


def catalog(epoch: str, sequence: int = 0, aircraft: str = "FA-18C_hornet"):
    return TelemetryCatalog(
        epoch, sequence, aircraft, 0, 1, [ENTRY]
    ).to_control()


def snapshot(epoch: str, sequence: int = 1, value: int = 1):
    return TelemetrySnapshot(
        epoch,
        sequence,
        "FA-18C_hornet",
        0,
        1,
        [DecodedValue(IDENTITY, True, value)],
    ).to_control()


def delta(epoch: str, sequence: int, value: int = 0):
    return TelemetryDelta(
        epoch,
        sequence,
        "FA-18C_hornet",
        0,
        1,
        [DecodedValue(IDENTITY, True, value)],
    ).to_control()


def test_ingress_requires_catalog_snapshot_then_contiguous_deltas() -> None:
    ingress = TelemetryIngress()
    epoch = str(uuid4())

    reset = ingress.accept(catalog(epoch))
    initial = ingress.accept(snapshot(epoch))
    changed = ingress.accept(delta(epoch, 2))

    assert reset is not None and reset.kind == "reset"
    assert initial is not None and initial.kind == "snapshot"
    assert initial.catalog == (ENTRY,)
    assert changed is not None and changed.kind == "delta"
    assert changed.values[0].value == 0
    assert ingress.ready


@pytest.mark.parametrize("sequence", [1, 3])
def test_ingress_rejects_stale_or_out_of_order_deltas(sequence: int) -> None:
    ingress = TelemetryIngress()
    epoch = str(uuid4())
    ingress.accept(catalog(epoch))
    ingress.accept(snapshot(epoch))

    with pytest.raises(TelemetryIngressError, match="out of order"):
        ingress.accept(delta(epoch, sequence))


def test_ingress_rejects_wrong_epoch_aircraft_and_unknown_controls() -> None:
    ingress = TelemetryIngress()
    epoch = str(uuid4())
    ingress.accept(catalog(epoch))
    ingress.accept(snapshot(epoch))

    with pytest.raises(TelemetryIngressError, match="wrong epoch"):
        ingress.accept(delta(str(uuid4()), 2))

    other = ControlIdentity("FA-18C_hornet", "APU_READY_LT", "integer", 0)
    unknown = TelemetryDelta(
        epoch,
        2,
        "FA-18C_hornet",
        0,
        1,
        [DecodedValue(other, True, 1)],
    )
    with pytest.raises(TelemetryIngressError, match="not present"):
        ingress.accept(unknown.to_control())


def test_fresh_epoch_resets_assembly_and_requires_a_full_snapshot() -> None:
    ingress = TelemetryIngress()
    first = str(uuid4())
    second = str(uuid4())
    ingress.accept(catalog(first))
    ingress.accept(snapshot(first))

    reset = ingress.accept(catalog(second))

    assert reset is not None and reset.kind == "reset"
    assert not ingress.ready
    with pytest.raises(TelemetryIngressError, match="initial snapshot"):
        ingress.accept(delta(second, 1))


def test_ingress_enforces_catalog_value_bounds() -> None:
    ingress = TelemetryIngress()
    epoch = str(uuid4())
    ingress.accept(catalog(epoch))

    with pytest.raises(TelemetryIngressError, match="catalog range"):
        ingress.accept(snapshot(epoch, value=3))
