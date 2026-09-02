from __future__ import annotations

from dcs_copilot.dcs.text_output import (
    MAX_TEXT_BYTES,
    DcsTextOutput,
    encode_text_datagram,
)
from dcs_copilot_protocol import ControlMessage


class FakeSocket:
    def __init__(self, *_args: object) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_text_datagram_is_bounded_and_keeps_valid_utf8() -> None:
    datagram = encode_text_datagram("  hello\nthere  " + "✈" * 2000)
    header, payload = datagram.split(b"\n", 1)

    assert header == f"MARA_TEXT/1 {len(payload)}".encode()
    assert payload.startswith(b"MARA: hello there")
    assert len(payload) <= MAX_TEXT_BYTES
    payload.decode("utf-8")


def test_only_assistant_text_is_forwarded_to_dcs_loopback() -> None:
    output = DcsTextOutput(port=9000, socket_factory=FakeSocket)  # type: ignore[arg-type]

    assert not output.accept(ControlMessage("pilot.text", {"text": "status"}))
    assert output.accept(ControlMessage("assistant.text", {"text": "Ready."}))

    fake = output._socket
    assert isinstance(fake, FakeSocket)
    assert fake.sent == [(b"MARA_TEXT/1 12\nMARA: Ready.", ("127.0.0.1", 9000))]

    output.close()
    assert fake.closed
