"""Compact binary media envelope for protocol version 2."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .messages import PROTOCOL_VERSION, ProtocolError, UnsupportedProtocolVersion

MAGIC = b"DCSC"
HEADER = struct.Struct("!4sBBIQ")


class MediaKind(IntEnum):
    AUDIO_INPUT = 1
    AUDIO_OUTPUT = 2


@dataclass(frozen=True, slots=True)
class AudioFormat:
    encoding: str = "pcm_s16le"
    sample_rate: int = 16_000
    channels: int = 1
    chunk_ms: int = 20

    def __post_init__(self) -> None:
        if self.encoding != "pcm_s16le":
            raise ProtocolError("only pcm_s16le audio is supported in protocol v2")
        if self.sample_rate <= 0 or self.channels <= 0 or self.chunk_ms <= 0:
            raise ProtocolError("audio format values must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "chunk_ms": self.chunk_ms,
        }

    @classmethod
    def from_dict(cls, payload: object) -> AudioFormat:
        if not isinstance(payload, dict):
            raise ProtocolError("audio format must be an object")
        encoding = payload.get("encoding")
        sample_rate = payload.get("sample_rate")
        channels = payload.get("channels")
        chunk_ms = payload.get("chunk_ms")
        if encoding != "pcm_s16le":
            raise ProtocolError("only pcm_s16le audio is supported in protocol v2")
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ProtocolError("audio sample_rate must be a positive integer")
        if not isinstance(channels, int) or channels <= 0:
            raise ProtocolError("audio channels must be a positive integer")
        if not isinstance(chunk_ms, int) or chunk_ms <= 0:
            raise ProtocolError("audio chunk_ms must be a positive integer")
        return cls(encoding, sample_rate, channels, chunk_ms)


@dataclass(frozen=True, slots=True)
class MediaPacket:
    kind: MediaKind
    sequence: int
    timestamp_ms: int
    payload: bytes
    protocol_version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise UnsupportedProtocolVersion(
                f"unsupported protocol version {self.protocol_version}"
            )
        if not self.payload:
            raise ProtocolError("media packet payload cannot be empty")

    def to_bytes(self) -> bytes:
        if not 0 <= self.sequence <= 0xFFFFFFFF:
            raise ProtocolError("media sequence must fit uint32")
        if not 0 <= self.timestamp_ms <= 0xFFFFFFFFFFFFFFFF:
            raise ProtocolError("media timestamp_ms must fit uint64")
        return (
            HEADER.pack(
                MAGIC,
                self.protocol_version,
                int(self.kind),
                self.sequence,
                self.timestamp_ms,
            )
            + self.payload
        )

    @classmethod
    def from_bytes(cls, raw: bytes) -> MediaPacket:
        if len(raw) < HEADER.size:
            raise ProtocolError("media packet is shorter than its header")
        magic, version, encoded_kind, sequence, timestamp_ms = HEADER.unpack_from(raw)
        if magic != MAGIC:
            raise ProtocolError("invalid media packet magic")
        if version != PROTOCOL_VERSION:
            raise UnsupportedProtocolVersion(f"unsupported protocol version {version}")
        try:
            kind = MediaKind(encoded_kind)
        except ValueError as exc:
            raise ProtocolError(f"unknown media kind {encoded_kind}") from exc
        payload = raw[HEADER.size :]
        if not payload:
            raise ProtocolError("media packet payload cannot be empty")
        return cls(kind, sequence, timestamp_ms, payload, version)
