from __future__ import annotations

from conftest import set_control
from dcs_copilot.aircraft.generic import GenericAircraftAdapter
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState


def test_normalizes_available_common_data(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    set_control(
        normalization_registry, state, "CommonData", "IAS_US_INT", 325, timestamp=10
    )
    set_control(
        normalization_registry, state, "CommonData", "ALT_MSL_FT", 12000, timestamp=10
    )
    set_control(
        normalization_registry, state, "CommonData", "HDG_DEG_MAG", 270, timestamp=10
    )
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_HIGH",
        0,
        timestamp=10,
    )
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        100,
        timestamp=10,
    )

    adapter = GenericAircraftAdapter(normalization_registry)
    first = adapter.normalize(state, now=10, stale_timeout=30)
    assert not first.values["indicated_airspeed"].available
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        101,
        timestamp=11,
    )
    partial = adapter.normalize(state, now=11, stale_timeout=30)

    assert partial.values["indicated_airspeed"].value == 325.0
    assert partial.values["altitude_msl"].value == 12000.0
    assert partial.values["heading"].value == 270.0
    assert partial.values["heading"].source == "DCS-BIOS:CommonData/HDG_DEG_MAG"


def test_missing_and_stale_common_data_are_explicit(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    set_control(
        normalization_registry, state, "CommonData", "IAS_US_INT", 100, timestamp=1
    )
    for identifier, value in {"TIME_MODEL_HIGH": 0, "TIME_MODEL_LOW": 100}.items():
        set_control(
            normalization_registry,
            state,
            "CommonData",
            identifier,
            value,
            timestamp=1,
        )
    adapter = GenericAircraftAdapter(normalization_registry)
    adapter.normalize(state, now=1, stale_timeout=30)
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        101,
        timestamp=2,
    )
    adapter.normalize(state, now=2, stale_timeout=30)
    partial = adapter.normalize(state, now=5, stale_timeout=30)
    assert not partial.values["indicated_airspeed"].available
    assert not partial.values["indicated_airspeed"].usable
    assert not partial.values["altitude_msl"].available
