"""Dependency-free process resource measurements for diagnostics."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    wall_time: float
    process_cpu_time: float
    resident_memory_bytes: int | None

    @classmethod
    def capture(cls) -> ResourceSnapshot:
        return cls(time.perf_counter(), time.process_time(), resident_memory_bytes())

    def cpu_percent_until(self, later: ResourceSnapshot) -> float:
        elapsed = max(0.0, later.wall_time - self.wall_time)
        if elapsed == 0.0:
            return 0.0
        cpu = max(0.0, later.process_cpu_time - self.process_cpu_time)
        return cpu / elapsed * 100.0


def resident_memory_bytes() -> int | None:
    """Return process RSS/high-water RSS without adding a client dependency."""

    if sys.platform == "win32":
        return _windows_resident_memory_bytes()
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux and the BSDs traditionally report KiB.
    return int(usage if sys.platform == "darwin" else usage * 1024)


def _windows_resident_memory_bytes() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        success = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if success else None
    except (AttributeError, OSError):
        return None


def format_bytes(value: int | None) -> str:
    if value is None:
        return "unavailable"
    mebibytes = value / (1024 * 1024)
    return f"{mebibytes:.1f} MiB"
