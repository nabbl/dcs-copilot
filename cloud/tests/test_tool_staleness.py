from __future__ import annotations

from dcs_copilot_cloud.aircraft.raw import RawTelemetryKey
from dcs_copilot_cloud.state.store import AircraftStateStore
from dcs_copilot_cloud.tools import (
    AircraftToolName,
    AircraftToolRequest,
    BackendAircraftToolExecutor,
)


def test_tools_recompute_staleness_when_no_new_delta_arrives() -> None:
    store = AircraftStateStore(value_stale_timeout=30.0)
    store.raw.update(
        RawTelemetryKey("FA-18C_hornet", "BATTERY_SW", "integer", 0),
        0,
        received_at=100.0,
    )
    store.update(aircraft="FA-18C_hornet", connected=True, now=100.0)
    executor = BackendAircraftToolExecutor(store, clock=lambda: 131.0)

    state = executor.execute(
        AircraftToolRequest.create(
            AircraftToolName.GET_AIRCRAFT_STATE,
            {"fields": ["battery_on"]},
        )
    )
    checklist = executor.execute(
        AircraftToolRequest.create(
            AircraftToolName.GET_CHECKLIST_STATUS,
            {
                "checklist_id": "fa18c_startup",
                "stage": "pre-start",
                "include_complete": True,
            },
        )
    )
    battery = next(item for item in checklist["items"] if item["id"] == "battery_on")

    assert state["fields"]["battery_on"]["status"] == "STALE"
    assert battery["status"] == "unconfirmed"
    assert checklist["complete"] is False
