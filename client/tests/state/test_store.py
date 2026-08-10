from __future__ import annotations

from conftest import set_control
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState
from dcs_copilot.state.models import FlightPhase
from dcs_copilot.state.phase_detector import FlightPhaseDetector, PhaseDetectorConfig
from dcs_copilot.state.store import AircraftStateStore


def test_store_normalizes_without_live_client_for_replay_paths(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    bios_state = DcsBiosState()
    for identifier, value in {
        "IAS_US_INT": 250,
        "ALT_MSL_FT": 10000,
        "HDG_DEG_MAG": 180,
        "TIME_MODEL_HIGH": 0,
        "TIME_MODEL_LOW": 100,
    }.items():
        set_control(
            normalization_registry,
            bios_state,
            "CommonData",
            identifier,
            value,
            timestamp=10,
        )
    for identifier, value in {
        "GEAR_LEVER": 0,
        "FLP_LG_NOSE_GEAR_LT": 0,
        "FLP_LG_LEFT_GEAR_LT": 0,
        "FLP_LG_RIGHT_GEAR_LT": 0,
        "EXT_WOW_NOSE": 0,
        "EXT_WOW_LEFT": 0,
        "EXT_WOW_RIGHT": 0,
        "EXT_REFUEL_PROBE": 0,
        "IFEI_RPM_L": " 70",
        "IFEI_RPM_R": " 70",
    }.items():
        set_control(
            normalization_registry,
            bios_state,
            "FA-18C_hornet",
            identifier,
            value,
            timestamp=10,
        )
    detector = FlightPhaseDetector(
        PhaseDetectorConfig(default_dwell_seconds=0, phase_dwell_seconds={})
    )
    store = AircraftStateStore(
        normalization_registry,
        bios_state=bios_state,
        phase_detector=detector,
    )
    changes = []
    store.add_change_callback(changes.append)

    first = store.update(connected=True, aircraft="FA-18C_hornet", now=10)
    assert not first.indicated_airspeed.available
    set_control(
        normalization_registry,
        bios_state,
        "CommonData",
        "TIME_MODEL_LOW",
        101,
        timestamp=14,
    )
    state = store.update(connected=True, aircraft="FA-18C_hornet", now=14)

    assert state.indicated_airspeed.value == 250
    assert state.gear_position.value == "UP"
    assert state.flight_phase is FlightPhase.CRUISE
    assert {change.field for change in changes} >= {
        "aircraft",
        "connected",
        "indicated_airspeed",
        "flight_phase",
    }


def test_store_disconnect_clears_normalized_availability(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    store = AircraftStateStore(normalization_registry, bios_state=DcsBiosState())
    state = store.update(connected=False, aircraft="FA-18C_hornet", now=1)
    assert not state.connected
    assert not state.indicated_airspeed.available
    assert state.flight_phase is FlightPhase.UNKNOWN


def test_store_drives_rule_engine_from_normalized_live_path(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    bios_state = DcsBiosState()
    set_control(
        normalization_registry,
        bios_state,
        "FA-18C_hornet",
        "MASTER_CAUTION_LT",
        1,
        timestamp=10,
    )
    store = AircraftStateStore(normalization_registry, bios_state=bios_state)
    transitions = []
    store.rule_engine.add_transition_callback(transitions.append)

    store.update(connected=True, aircraft="FA-18C_hornet", now=10)
    store.update(connected=True, aircraft="FA-18C_hornet", now=10.25)
    assert store.rule_engine.active_issues[0].rule_id == "FA18_MASTER_CAUTION"

    set_control(
        normalization_registry,
        bios_state,
        "FA-18C_hornet",
        "MASTER_CAUTION_LT",
        0,
        timestamp=11,
    )
    store.update(connected=True, aircraft="FA-18C_hornet", now=11)
    store.update(connected=True, aircraft="FA-18C_hornet", now=11.5)
    assert store.rule_engine.active_issues == ()
    assert [item.type for item in transitions] == ["ACTIVATED", "RESOLVED"]
