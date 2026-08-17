from __future__ import annotations

import pytest

from dcs_copilot.dcs.indications import (
    DcsIndicationReader,
    IndicationPacketAssembler,
    IndicationProtocolError,
)


TOKEN = "abcdef0123456789"


def _packet(
    *,
    sequence: int = 4,
    indicator: int = 7,
    chunk: int = 0,
    count: int = 1,
    status: str = "OK",
    payload: bytes = b"radar_mode = RWS",
) -> bytes:
    header = (
        f"MARA_INDICATION 1 {TOKEN} {sequence} {indicator} {chunk} {count} "
        f"1720000000.25 {status} {len(payload)}\n"
    ).encode("ascii")
    return header + payload


def test_packet_assembler_preserves_raw_output() -> None:
    assembler = IndicationPacketAssembler(TOKEN)

    state = assembler.feed(_packet(), received_at=1720000001.0)

    assert state is not None
    assert state.indicator_id == 7
    assert state.raw == "radar_mode = RWS"
    assert state.error is None
    assert state.observed_at == 1720000000.25
    assert state.received_at == 1720000001.0


def test_packet_assembler_reassembles_out_of_order_chunks() -> None:
    assembler = IndicationPacketAssembler(TOKEN)

    assert assembler.feed(_packet(chunk=1, count=2, payload=b"RWS")) is None
    state = assembler.feed(_packet(chunk=0, count=2, payload=b"mode="))

    assert state is not None
    assert state.raw == "mode=RWS"


def test_packet_assembler_reports_probe_errors_as_unavailable() -> None:
    assembler = IndicationPacketAssembler(TOKEN)

    state = assembler.feed(_packet(status="ERROR", payload=b"function unavailable"))

    assert state is not None
    assert state.raw == ""
    assert state.error == "function unavailable"


def test_packet_assembler_ignores_another_request_token() -> None:
    assembler = IndicationPacketAssembler("00000000")

    assert assembler.feed(_packet()) is None


def test_packet_assembler_rejects_invalid_payload_length() -> None:
    assembler = IndicationPacketAssembler(TOKEN)

    with pytest.raises(IndicationProtocolError, match="payload length"):
        assembler.feed(_packet()[:-1])


def test_reader_rejects_an_excessive_indicator_range() -> None:
    reader = DcsIndicationReader()

    with pytest.raises(ValueError, match="more than 64"):
        reader.scan(0, 64, timeout=0)
