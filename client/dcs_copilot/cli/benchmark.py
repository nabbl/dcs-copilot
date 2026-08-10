"""CLI for the dependency-free client performance workload."""

from __future__ import annotations

from dcs_copilot.diagnostics.benchmark import run_client_benchmark
from dcs_copilot.diagnostics.resources import format_bytes


def run_benchmark(*, updates: int, idle_seconds: float) -> int:
    try:
        result = run_client_benchmark(updates=updates, idle_seconds=idle_seconds)
    except ValueError as exc:
        print(f"Benchmark failed: {exc}")
        return 2
    print(f"Idle sample: {result.idle_wall_seconds:.3f} s")
    print(f"Idle CPU: {result.idle_cpu_percent:.3f}%")
    print(f"Resident memory before: {format_bytes(result.resident_memory_before)}")
    print(f"Synthetic updates: {result.updates}")
    print(f"DCS-BIOS frames parsed: {result.parser_frames}")
    print(f"Bytes parsed: {result.bytes_processed}")
    print(f"Workload time: {result.workload_wall_seconds:.3f} s")
    print(f"Workload CPU time: {result.workload_cpu_seconds:.3f} s")
    print(f"Throughput: {result.updates_per_second:.0f} updates/s")
    print(f"Estimated CPU at 30 Hz: {result.estimated_cpu_percent_at_30hz:.3f}%")
    print(f"Resident memory after: {format_bytes(result.resident_memory_after)}")
    print("AI inference running locally: NO")
    return 0
