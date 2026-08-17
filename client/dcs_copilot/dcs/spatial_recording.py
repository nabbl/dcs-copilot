"""Explicit opt-in recording of normalized Coach telemetry for replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from dcs_copilot_protocol import CoachTelemetry

MAX_LINE_BYTES = 256 * 1024
MAX_RECORDING_BYTES = 128 * 1024 * 1024


class SpatialRecordingWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._output: TextIO | None = None
        self._bytes_written = 0

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._output = self.path.open("w", encoding="utf-8", newline="\n")
        self._bytes_written = 0

    def write(self, telemetry: CoachTelemetry) -> None:
        if self._output is None:
            raise RuntimeError("spatial recording writer is not open")
        document = {
            "t": telemetry.observed_at_ms / 1000.0,
            "telemetry": telemetry.to_control().payload,
        }
        encoded = json.dumps(document, separators=(",", ":"))
        encoded_bytes = len(encoded.encode("utf-8")) + 1
        if encoded_bytes > MAX_LINE_BYTES:
            raise RuntimeError("spatial recording line exceeds 256 KiB")
        if self._bytes_written + encoded_bytes > MAX_RECORDING_BYTES:
            raise RuntimeError("spatial recording reached the 128 MiB limit")
        self._output.write(encoded + "\n")
        self._bytes_written += encoded_bytes

    def close(self) -> None:
        if self._output is not None:
            self._output.close()
            self._output = None
