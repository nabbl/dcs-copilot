from __future__ import annotations

import socket
import struct
import time
from pathlib import Path

from conftest import protocol_frame, protocol_write
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry


class FakeSocket:
    def __init__(self) -> None:
        self.options: list[tuple[int, int, object]] = []
        self.bound: tuple[str, int] | None = None
        self.blocking: bool | None = None
        self.closed = False

    def setsockopt(self, level: int, option: int, value: object) -> None:
        self.options.append((level, option, value))

    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address

    def setblocking(self, value: bool) -> None:
        self.blocking = value

    def close(self) -> None:
        self.closed = True


def test_socket_uses_reuseaddr_and_loopback_multicast_membership() -> None:
    fake = FakeSocket()
    client = DcsBiosClient(socket_factory=lambda *_args: fake)  # type: ignore[arg-type]
    client.open()

    assert fake.bound == ("", 5010)
    assert fake.blocking is False
    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in fake.options
    expected = socket.inet_aton("239.255.50.10") + socket.inet_aton("127.0.0.1")
    assert (socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, expected) in fake.options

    client.close()
    assert fake.closed


def test_detects_aircraft_and_emits_only_changed_controls(bios_json_dir: Path) -> None:
    registry = DcsBiosControlRegistry.from_path(bios_json_dir)
    client = DcsBiosClient(registry=registry)
    changes = []
    client.add_change_callback(changes.append)
    aircraft = b"FA-18C_hornet\x00".ljust(24, b"\x00")
    stream = (
        protocol_frame(
            protocol_write(0, aircraft), protocol_write(0x7400, struct.pack("<H", 8))
        )
        + b"\x55" * 4
    )

    client.parser.feed(stream)

    assert client.current_aircraft == "FA-18C_hornet"
    assert client.connected
    assert {(item.control.identifier, item.value) for item in changes} == {
        ("_ACFT_NAME", "FA-18C_hornet"),
        ("MASTER_CAUTION_LT", 1),
    }

    client.parser.feed(
        protocol_frame(protocol_write(0x7400, struct.pack("<H", 8))) + b"\x55" * 4
    )
    assert len(changes) == 2


def test_connection_becomes_stale_without_frames() -> None:
    client = DcsBiosClient(stale_timeout=0.01)
    client._connected = True
    client.state.apply_write(0, b"\x01\x00")
    client.latest_frame_at = time.monotonic() - 1
    assert not client.connected
    assert client.state.read(0, 2) is None


def test_aircraft_change_invalidates_values_not_written_in_new_frame(
    bios_json_dir: Path,
) -> None:
    registry = DcsBiosControlRegistry.from_path(bios_json_dir)
    client = DcsBiosClient(registry=registry)
    hornet = b"FA-18C_hornet\x00".ljust(24, b"\x00")
    client.parser.feed(
        protocol_frame(
            protocol_write(0, hornet),
            protocol_write(0x7400, struct.pack("<H", 8)),
        )
        + b"\x55" * 4
    )
    assert client.state.read(0x7400, 2) == b"\x08\x00"

    viper = b"F-16C_50\x00".ljust(24, b"\x00")
    client.parser.feed(protocol_frame(protocol_write(0, viper)) + b"\x55" * 4)

    assert client.current_aircraft == "F-16C_50"
    assert client.state.read(0x7400, 2) is None
