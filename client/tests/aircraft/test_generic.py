from __future__ import annotations

import pytest

from conftest import set_control
from dcs_copilot.aircraft.generic import GenericAircraftAdapter
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState


def set_position(
    registry: DcsBiosControlRegistry,
    state: DcsBiosState,
    *,
    longitude_fraction: int,
    timestamp: float,
) -> None:
    for identifier, value in {
        "LAT_DEG": 0,
        "LAT_SEC": 0,
        "LAT_SEC_FRAC": 0,
        "LAT_Z_DIR": "N",
        "LON_DEG": 0,
        "LON_SEC": 0,
        "LON_SEC_FRAC": longitude_fraction,
        "LON_Z_DIR": "E",
    }.items():
        set_control(
            registry,
            state,
            "CommonData",
            identifier,
            value,
            timestamp=timestamp,
        )


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


def test_ground_speed_uses_position_delta_instead_of_wind_affected_ias(
    normalization_registry: DcsBiosControlRegistry,
) -> None:
    state = DcsBiosState()
    for identifier, value in {
        "IAS_US_INT": 12,
        "TIME_MODEL_HIGH": 0,
        "TIME_MODEL_LOW": 100,
    }.items():
        set_control(
            normalization_registry,
            state,
            "CommonData",
            identifier,
            value,
            timestamp=1,
        )
    set_position(
        normalization_registry,
        state,
        longitude_fraction=0,
        timestamp=1,
    )
    adapter = GenericAircraftAdapter(normalization_registry)
    adapter.normalize(state, now=1, stale_timeout=30)

    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        200,
        timestamp=2,
    )
    adapter.normalize(state, now=2, stale_timeout=30)
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        300,
        timestamp=3,
    )
    stationary = adapter.normalize(state, now=3, stale_timeout=30)

    assert stationary.values["indicated_airspeed"].value == 12
    assert stationary.values["ground_speed"].value == 0

    set_position(
        normalization_registry,
        state,
        longitude_fraction=182,
        timestamp=4,
    )
    set_control(
        normalization_registry,
        state,
        "CommonData",
        "TIME_MODEL_LOW",
        400,
        timestamp=4,
    )
    moving = adapter.normalize(state, now=4, stale_timeout=30)
    assert moving.values["ground_speed"].value == pytest.approx(10.0, abs=0.2)
    assert not any(name.startswith(("LAT_", "LON_")) for name in moving.raw)
