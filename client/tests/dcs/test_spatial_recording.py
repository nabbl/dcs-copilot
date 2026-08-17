from __future__ import annotations

import json
from pathlib import Path

from dcs_copilot.dcs.spatial_recording import SpatialRecordingWriter
from dcs_copilot_protocol import CoachCapabilitiesPayload, CoachTelemetry


def test_spatial_recording_writes_replay_compatible_normalized_jsonl(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flight.jsonl"
    writer = SpatialRecordingWriter(path)
    writer.open()
    writer.write(
        CoachTelemetry(
            sequence=1,
            observed_at_ms=1250,
            capabilities=CoachCapabilitiesPayload(True, False, False, True),
        )
    )
    writer.close()

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["t"] == 1.25
    assert document["telemetry"]["sequence"] == 1
    assert document["telemetry"]["references"] == []
