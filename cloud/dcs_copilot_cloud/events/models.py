"""Cloud-domain aircraft event models (independent of shared protocol)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CloudAircraftEvent:
    event_id: str
    rule_id: str
    status: str  # "RAISED", "RESOLVED", "DISABLED"
    severity: str  # "INFO", "ADVISORY", "WARNING", "CRITICAL"
    aircraft: str
    flight_phase: str | None
    message: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CloudManagedEvent:
    event: CloudAircraftEvent
    observed_at: float
    publish: bool
    speak: bool
