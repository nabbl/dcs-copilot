from __future__ import annotations

from conftest import encode_control_value, protocol_frame, protocol_write
from dcs_copilot.dcs.bios_client import DcsBiosClient
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.state.models import FlightPhase
from dcs_copilot.state.phase_detector import FlightPhaseDetector, PhaseDetectorConfig
from dcs_copilot.state.store import AircraftStateStore


def write(
    registry: DcsBiosControlRegistry,
    module: str,
    identifier: str,
    value: int | str,
) -> bytes:
    address, data = encode_control_value(registry, module, identifier, value)
    if len(data) % 2:
        data += b"\x00"
    return protocol_write(address, data)


def test_client_frames_drive_normalized_store(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    client = DcsBiosClient(registry=normalization_registry)
    detector = FlightPhaseDetector(
        PhaseDetectorConfig(default_dwell_seconds=0, phase_dwell_seconds={})
    )
    store = AircraftStateStore(
        normalization_registry, client=client, phase_detector=detector
    )
    static_writes = [
        write(normalization_registry, "MetadataStart", "_ACFT_NAME", "FA-18C_hornet"),
        write(normalization_registry, "CommonData", "TIME_MODEL_HIGH", 0),
        write(normalization_registry, "CommonData", "IAS_US_INT", 140),
        write(normalization_registry, "CommonData", "ALT_MSL_FT", 10000),
        write(normalization_registry, "CommonData", "HDG_DEG_MAG", 180),
        write(normalization_registry, "FA-18C_hornet", "GEAR_LEVER", 1),
        write(normalization_registry, "FA-18C_hornet", "FLP_LG_NOSE_GEAR_LT", 1),
        write(normalization_registry, "FA-18C_hornet", "FLP_LG_LEFT_GEAR_LT", 1),
        write(normalization_registry, "FA-18C_hornet", "FLP_LG_RIGHT_GEAR_LT", 1),
        write(normalization_registry, "FA-18C_hornet", "EXT_WOW_NOSE", 0),
        write(normalization_registry, "FA-18C_hornet", "EXT_WOW_LEFT", 0),
        write(normalization_registry, "FA-18C_hornet", "EXT_WOW_RIGHT", 0),
        write(normalization_registry, "FA-18C_hornet", "EXT_REFUEL_PROBE", 0),
        write(normalization_registry, "FA-18C_hornet", "IFEI_RPM_L", "70"),
        write(normalization_registry, "FA-18C_hornet", "IFEI_RPM_R", "70"),
    ]
    first = protocol_frame(
        *static_writes,
        write(normalization_registry, "CommonData", "TIME_MODEL_LOW", 100),
    )
    second = protocol_frame(
        write(normalization_registry, "CommonData", "TIME_MODEL_LOW", 101)
    )

    client.parser.feed(first + second + b"\x55" * 4)

    assert client.current_aircraft == "FA-18C_hornet"
    assert store.current.connected
    assert store.current.indicated_airspeed.value == 140
    assert store.current.flight_phase is FlightPhase.APPROACH
