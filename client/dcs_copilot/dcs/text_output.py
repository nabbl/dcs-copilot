"""Bounded loopback transport for MARA's in-game DCS text notifications."""

from __future__ import annotations

import socket
from typing import Protocol

from dcs_copilot_protocol import ControlMessage


PROTOCOL = "MARA_TEXT"
PROTOCOL_VERSION = 1
DEFAULT_PORT = 7782
MAX_TEXT_BYTES = 4096


class DatagramSocket(Protocol):
    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...

    def close(self) -> None: ...


def encode_text_datagram(text: str) -> bytes:
    """Encode one visible MARA message without splitting a UTF-8 code point."""

    visible = " ".join(text.replace("\x00", "").split())
    if not visible:
        raise ValueError("MARA text output cannot be empty")
    payload = f"MARA: {visible}".encode("utf-8")
    if len(payload) > MAX_TEXT_BYTES:
        payload = payload[:MAX_TEXT_BYTES]
        while True:
            try:
                payload.decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                payload = payload[: exc.start]
    header = f"{PROTOCOL}/{PROTOCOL_VERSION} {len(payload)}\n".encode("ascii")
    return header + payload


class DcsTextOutput:
    """Send final assistant text to the loopback-only DCS user hook."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        socket_factory: type[socket.socket] = socket.socket,
    ) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("DCS text output port must be between 1 and 65535")
        self.port = port
        self._socket: DatagramSocket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)

    def accept(self, message: ControlMessage) -> bool:
        if message.type != "assistant.text":
            return False
        text = message.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return False
        datagram = encode_text_datagram(text)
        try:
            return self._socket.sendto(datagram, ("127.0.0.1", self.port)) == len(
                datagram
            )
        except OSError:
            return False

    def close(self) -> None:
        self._socket.close()
