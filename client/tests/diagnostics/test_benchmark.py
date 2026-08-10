from __future__ import annotations

from dcs_copilot.diagnostics.benchmark import run_client_benchmark
from dcs_copilot.diagnostics.resources import ResourceSnapshot, format_bytes


def test_benchmark_exercises_parser_and_deterministic_pipeline() -> None:
    result = run_client_benchmark(updates=60, idle_seconds=0)
    assert result.updates == 60
    assert result.parser_frames == 60
    assert result.bytes_processed == 610
    assert result.workload_cpu_seconds >= 0
    assert result.estimated_cpu_percent_at_30hz >= 0


def test_resource_snapshot_cpu_and_memory_formatting() -> None:
    start = ResourceSnapshot(10.0, 2.0, 1024 * 1024)
    end = ResourceSnapshot(12.0, 2.5, 2 * 1024 * 1024)
    assert start.cpu_percent_until(end) == 25.0
    assert format_bytes(end.resident_memory_bytes) == "2.0 MiB"
    assert format_bytes(None) == "unavailable"
