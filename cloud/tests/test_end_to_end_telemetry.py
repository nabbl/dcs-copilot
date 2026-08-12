from __future__ import annotations

import json
import struct
from pathlib import Path

from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.telemetry import TelemetryPublisher
from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey
from dcs_copilot_cloud.state.store import AircraftStateStore
from dcs_copilot_cloud.telemetry import TelemetryBatch, TelemetryIngress
from dcs_copilot_cloud.tools import (
    AircraftToolName,
    AircraftToolRequest,
    BackendAircraftToolExecutor,
)
from dcs_copilot_protocol import ControlMessage


def _write(address: int, data: bytes) -> bytes:
    return struct.pack("<HH", address, len(data)) + data


def _frame(*writes: bytes) -> bytes:
    return b"\x55" * 4 + b"".join(writes) + b"\x55" * 4


def _integer_control(address: int, maximum: int) -> dict[str, object]:
    return {
        "outputs": [
            {
                "type": "integer",
                "address": address,
                "mask": 0xFFFF,
                "shift_by": 0,
                "max_value": maximum,
            }
        ]
    }


def _string_control(address: int, length: int) -> dict[str, object]:
    return {
        "outputs": [
            {
                "type": "string",
                "address": address,
                "max_length": length,
            }
        ]
    }


def _registry(tmp_path: Path) -> DcsBiosControlRegistry:
    metadata = {
        "Metadata": {
            "_ACFT_NAME": {
                "identifier": "_ACFT_NAME",
                **_string_control(0, 24),
            }
        }
    }
    hornet = {
        "Startup": {
            identifier: {"identifier": identifier, **definition}
            for identifier, definition in {
                "BATTERY_SW": _integer_control(0x7400, 2),
                "APU_READY_LT": _integer_control(0x7402, 1),
                "EMERGENCY_PARKING_BRAKE_PULL": _integer_control(0x7404, 1),
                "IFEI_RPM_L": _string_control(0x7410, 8),
                "IFEI_RPM_R": _string_control(0x7418, 8),
            }.items()
        }
    }
    (tmp_path / "MetadataStart.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "FA-18C_hornet.json").write_text(json.dumps(hornet), encoding="utf-8")
    (tmp_path / "AircraftAliases.json").write_text(
        json.dumps({"FA-18C_hornet": ["FA-18C_hornet"]}),
        encoding="utf-8",
    )
    return DcsBiosControlRegistry.from_path(tmp_path)


def _apply(store: AircraftStateStore, batch: TelemetryBatch, *, now: float) -> None:
    if batch.kind == "reset":
        store.raw.reset()
        store.update(aircraft=None, connected=False, now=now)
        return
    for entry in batch.catalog:
        identity = entry.identity
        store.raw.catalog_register(
            RawTelemetryKey(
                identity.module,
                identity.identifier,
                identity.output_type,
                identity.output_index,
            ),
            max_value=entry.integer_max,
        )
    if batch.kind == "snapshot":
        store.raw.clear()
    for decoded in batch.values:
        identity = decoded.identity
        key = RawTelemetryKey(
            identity.module,
            identity.identifier,
            identity.output_type,
            identity.output_index,
        )
        if decoded.available:
            assert decoded.value is not None
            store.raw.update(key, decoded.value, received_at=now)
        else:
            store.raw.mark_unavailable(key)
    store.update(aircraft=batch.aircraft, connected=True, now=now)


def test_decoded_cold_dark_hornet_reaches_backend_checklist_tool(
    tmp_path: Path,
) -> None:
    messages: list[ControlMessage] = []
    client = DcsBiosClient(registry=_registry(tmp_path))
    publisher = TelemetryPublisher(
        client,
        lambda message: messages.append(message) is None,
    )
    aircraft = b"FA-18C_hornet\x00".ljust(24, b"\x00")
    client.parser.feed(
        _frame(
            _write(0, aircraft),
            _write(0x7400, struct.pack("<H", 1)),
            _write(0x7402, struct.pack("<H", 0)),
            _write(0x7404, struct.pack("<H", 1)),
            _write(0x7410, b"0\x00".ljust(8, b"\x00")),
            _write(0x7418, b"0\x00".ljust(8, b"\x00")),
        )
    )
    publisher.set_session_active(True)
    publisher.flush()

    ingress = TelemetryIngress()
    store = AircraftStateStore()
    for message in messages:
        batch = ingress.accept(message)
        if batch is not None:
            _apply(store, batch, now=100.0)

    result = BackendAircraftToolExecutor(store, clock=lambda: 100.0).execute(
        AircraftToolRequest.create(
            AircraftToolName.GET_MISSING_CHECKLIST_ITEMS,
            {
                "checklist_id": "fa18c_startup",
                "stage": "before-taxi",
                "include_complete": False,
            },
        )
    )
    unresolved = {item["id"]: item["status"] for item in result["items"]}

    assert store.current.battery_on.value is False
    assert unresolved["battery_on"] == "incomplete"
    assert unresolved["apu_ready"] == "incomplete"
    assert unresolved["left_engine_running"] == "incomplete"
    assert unresolved["right_engine_running"] == "incomplete"
    assert result["complete"] is False
