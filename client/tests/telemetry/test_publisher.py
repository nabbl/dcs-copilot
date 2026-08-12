from __future__ import annotations

import struct
from pathlib import Path

from conftest import protocol_frame, protocol_write
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.telemetry import TelemetryPublisher
from dcs_copilot_protocol import (
    ControlMessage,
    TelemetryCatalog,
    TelemetryDelta,
    TelemetrySnapshot,
)


def hornet_frame(caution: int) -> bytes:
    aircraft = b"FA-18C_hornet\x00".ljust(24, b"\x00")
    return (
        protocol_frame(
            protocol_write(0, aircraft),
            protocol_write(0x7400, struct.pack("<H", caution << 3)),
        )
        + b"\x55" * 4
    )


def publisher(
    bios_json_dir: Path,
    sent: list[ControlMessage],
    **kwargs,
) -> tuple[DcsBiosClient, TelemetryPublisher]:
    registry = DcsBiosControlRegistry.from_path(bios_json_dir)
    client = DcsBiosClient(registry=registry)
    telemetry = TelemetryPublisher(
        client,
        lambda message: sent.append(message) is None,
        **kwargs,
    )
    return client, telemetry


def test_initial_epoch_sends_catalog_then_complete_snapshot(
    bios_json_dir: Path,
) -> None:
    sent: list[ControlMessage] = []
    client, telemetry = publisher(bios_json_dir, sent)
    client.parser.feed(hornet_frame(1))

    telemetry.set_session_active(True)
    telemetry.flush()

    assert [message.type for message in sent] == [
        "telemetry.catalog",
        "telemetry.snapshot",
    ]
    catalog = TelemetryCatalog.from_control(sent[0])
    snapshot = TelemetrySnapshot.from_control(sent[1])
    assert catalog.epoch == snapshot.epoch
    assert catalog.sequence == 0
    assert snapshot.sequence == 1
    assert {entry.identity.identifier for entry in catalog.entries} == {
        "MASTER_CAUTION_LT",
        "UFC_SCRATCHPAD",
    }
    assert [(value.identity.identifier, value.value) for value in snapshot.values] == [
        ("MASTER_CAUTION_LT", 1)
    ]


def test_unchanged_outputs_are_not_sent_and_changed_outputs_are_deltas(
    bios_json_dir: Path,
) -> None:
    sent: list[ControlMessage] = []
    client, telemetry = publisher(bios_json_dir, sent)
    client.parser.feed(hornet_frame(0))
    telemetry.set_session_active(True)
    telemetry.flush()
    sent.clear()

    client.parser.feed(hornet_frame(0))
    telemetry.flush()
    assert sent == []

    client.parser.feed(hornet_frame(1))
    telemetry.flush()
    delta = TelemetryDelta.from_control(sent[0])
    assert [(value.identity.identifier, value.value) for value in delta.values] == [
        ("MASTER_CAUTION_LT", 1)
    ]


def test_rapid_switch_changes_are_bounded_and_coalesced(
    bios_json_dir: Path,
) -> None:
    sent: list[ControlMessage] = []
    client, telemetry = publisher(
        bios_json_dir,
        sent,
        max_pending_controls=1,
        max_switch_transitions=2,
    )
    client.parser.feed(hornet_frame(0))
    telemetry.set_session_active(True)
    telemetry.flush()
    sent.clear()

    for value in (1, 0, 1, 0, 1):
        client.parser.feed(hornet_frame(value))

    assert telemetry.pending_count <= 2
    assert telemetry.coalesced_values >= 1
    telemetry.flush()
    telemetry.flush()
    assert all(message.type == "telemetry.delta" for message in sent)


def test_reconnect_uses_a_new_epoch_and_full_snapshot(
    bios_json_dir: Path,
) -> None:
    sent: list[ControlMessage] = []
    client, telemetry = publisher(bios_json_dir, sent)
    client.parser.feed(hornet_frame(1))
    telemetry.set_session_active(True)
    telemetry.flush()
    first_epoch = TelemetryCatalog.from_control(sent[0]).epoch
    sent.clear()

    telemetry.set_session_active(False)
    telemetry.set_session_active(True)
    telemetry.flush()

    second_epoch = TelemetryCatalog.from_control(sent[0]).epoch
    assert second_epoch != first_epoch
    assert any(message.type == "telemetry.snapshot" for message in sent)
