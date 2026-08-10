from __future__ import annotations

import struct

from conftest import protocol_frame, protocol_write
from dcs_copilot.dcs.bios_protocol import DcsBiosProtocolParser


def test_parses_fragmented_writes_and_completes_at_next_sync() -> None:
    parser = DcsBiosProtocolParser()
    stream = (
        b"ignored noise"
        + protocol_frame(
            protocol_write(0x1000, struct.pack("<H", 0x1234)),
            protocol_write(0x1010, b"HORNET  \x00\x00"),
        )
        + b"\x55" * 4
    )

    completed = []
    for byte in stream:
        completed.extend(parser.feed(bytes([byte])))

    assert parser.bios_state.read(0x1000, 2) == b"\x34\x12"
    assert parser.bios_state.read(0x1010, 10) == b"HORNET  \x00\x00"
    assert len(completed) == 1
    assert len(completed[0].writes) == 2
    assert parser.error_count == 0


def test_short_runs_of_sync_byte_remain_payload_data() -> None:
    parser = DcsBiosProtocolParser()
    payload = b"\x55\x55\x01\x55\x02\x03"
    parser.feed(protocol_frame(protocol_write(0x2000, payload)) + b"\x55" * 4)
    assert parser.bios_state.read(0x2000, len(payload)) == payload


def test_multiple_frames_in_one_chunk() -> None:
    parser = DcsBiosProtocolParser()
    stream = (
        protocol_frame(protocol_write(0x20, b"\x01\x00"))
        + protocol_frame(protocol_write(0x20, b"\x02\x00"))
        + b"\x55" * 4
    )
    frames = parser.feed(stream)
    assert [frame.number for frame in frames] == [1, 2]
    assert parser.bios_state.read(0x20, 2) == b"\x02\x00"


def test_malformed_odd_count_waits_for_sync_and_recovers() -> None:
    parser = DcsBiosProtocolParser()
    corrupt = b"\x55" * 4 + struct.pack("<HH", 0x1000, 3) + b"junk"
    valid = protocol_frame(protocol_write(0x2000, b"\xaa\xbb")) + b"\x55" * 4

    frames = parser.feed(corrupt + valid)

    assert parser.error_count == 1
    assert parser.bios_state.read(0x1000, 3) is None
    assert parser.bios_state.read(0x2000, 2) == b"\xaa\xbb"
    assert len(frames) == 1


def test_out_of_bounds_write_is_malformed() -> None:
    parser = DcsBiosProtocolParser()
    parser.feed(b"\x55" * 4 + struct.pack("<HH", 0xFFFE, 4))
    assert parser.error_count == 1
    assert not parser.synchronized


def test_incomplete_write_is_not_applied_at_resync() -> None:
    parser = DcsBiosProtocolParser()
    parser.feed(b"\x55" * 4 + struct.pack("<HH", 0x3000, 4) + b"\x01\x02")
    parser.feed(b"\x55" * 4)
    assert parser.bios_state.read(0x3000, 4) is None
    assert parser.error_count == 1
