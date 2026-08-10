from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest
from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState


def protocol_write(address: int, data: bytes) -> bytes:
    return struct.pack("<HH", address, len(data)) + data


def protocol_frame(*writes: bytes) -> bytes:
    return b"\x55" * 4 + b"".join(writes)


@pytest.fixture
def bios_json_dir(tmp_path: Path) -> Path:
    json_dir = tmp_path / "Scripts" / "DCS-BIOS" / "doc" / "json"
    json_dir.mkdir(parents=True)
    metadata = {
        "Metadata": {
            "_ACFT_NAME": {
                "identifier": "_ACFT_NAME",
                "description": "Aircraft Name",
                "inputs": [],
                "outputs": [
                    {
                        "address": 0,
                        "description": "Aircraft Name",
                        "max_length": 24,
                        "type": "string",
                    }
                ],
            }
        }
    }
    hornet = {
        "Indicators": {
            "MASTER_CAUTION_LT": {
                "identifier": "MASTER_CAUTION_LT",
                "description": "Master caution light",
                "outputs": [
                    {
                        "address": 0x7400,
                        "mask": 0x0008,
                        "shift_by": 3,
                        "max_value": 1,
                        "type": "integer",
                    }
                ],
            },
            "UFC_SCRATCHPAD": {
                "identifier": "UFC_SCRATCHPAD",
                "outputs": [
                    {
                        "address": 0x7410,
                        "max_length": 8,
                        "type": "string",
                    }
                ],
            },
        }
    }
    (json_dir / "MetadataStart.json").write_text(json.dumps(metadata), encoding="utf-8")
    (json_dir / "FA-18C_hornet.json").write_text(json.dumps(hornet), encoding="utf-8")
    (json_dir / "AircraftAliases.json").write_text(
        json.dumps({"FA-18C_hornet": ["FA-18C_hornet"]})
    )
    return json_dir


def _integer_control(address: int, max_value: int) -> dict[str, Any]:
    bits = max(1, max_value.bit_length())
    mask = (1 << bits) - 1
    return {
        "outputs": [
            {
                "type": "integer",
                "address": address,
                "mask": mask,
                "shift_by": 0,
                "max_value": max_value,
            }
        ]
    }


def _string_control(address: int, length: int) -> dict[str, Any]:
    return {"outputs": [{"type": "string", "address": address, "max_length": length}]}


@pytest.fixture
def normalization_registry(tmp_path: Path) -> DcsBiosControlRegistry:
    metadata = {
        "Metadata": {
            "_ACFT_NAME": {
                "identifier": "_ACFT_NAME",
                **_string_control(0, 24),
            }
        }
    }
    (tmp_path / "MetadataStart.json").write_text(json.dumps(metadata), encoding="utf-8")
    common_specs = {
        "IAS_US_INT": (0x0400, 65535),
        "ALT_MSL_FT": (0x0402, 65535),
        "HDG_DEG_MAG": (0x0404, 359),
        "TIME_MODEL_HIGH": (0x0406, 65535),
        "TIME_MODEL_LOW": (0x0408, 65535),
    }
    common = {
        identifier: {"identifier": identifier, **_integer_control(address, maximum)}
        for identifier, (address, maximum) in common_specs.items()
    }
    (tmp_path / "CommonData.json").write_text(
        json.dumps({"Data": common}), encoding="utf-8"
    )

    integer_specs: dict[str, tuple[int, int]] = {}
    next_address = 0x7400
    one_bit = [
        "GEAR_LEVER",
        "FLP_LG_NOSE_GEAR_LT",
        "FLP_LG_LEFT_GEAR_LT",
        "FLP_LG_RIGHT_GEAR_LT",
        "EXT_WOW_NOSE",
        "EXT_WOW_LEFT",
        "EXT_WOW_RIGHT",
        "MASTER_ARM_SW",
        "EJECTION_SEAT_ARMED",
        "MASTER_CAUTION_LT",
        "CLIP_CK_SEAT_LT",
        "CLIP_APU_ACC_LT",
        "CLIP_BATT_SW_LT",
        "CLIP_FCS_HOT_LT",
        "CLIP_GEN_TIE_LT",
        "CLIP_FUEL_LO_LT",
        "CLIP_FCES_LT",
        "CLIP_L_GEN_LT",
        "CLIP_R_GEN_LT",
    ]
    for identifier in one_bit:
        integer_specs[identifier] = (next_address, 1)
        next_address += 2
    for identifier, maximum in {
        "FLAP_SW": 2,
        "EMERGENCY_PARKING_BRAKE_ROTATE": 2,
        "CANOPY_POS": 65535,
        "EXT_SPEED_BRAKE": 65535,
        "EXT_REFUEL_PROBE": 65535,
        "EXT_HOOK": 65535,
        "INT_THROTTLE_LEFT": 65535,
        "INT_THROTTLE_RIGHT": 65535,
    }.items():
        integer_specs[identifier] = (next_address, maximum)
        next_address += 2
    hornet = {
        identifier: {
            "identifier": identifier,
            **_integer_control(address, maximum),
        }
        for identifier, (address, maximum) in integer_specs.items()
    }
    for identifier, length in {
        "IFEI_FUEL_UP": 6,
        "IFEI_T": 6,
        "IFEI_RPM_L": 3,
        "IFEI_RPM_R": 3,
    }.items():
        hornet[identifier] = {
            "identifier": identifier,
            **_string_control(next_address, length),
        }
        next_address += length + (length % 2)
    (tmp_path / "FA-18C_hornet.json").write_text(
        json.dumps({"Cockpit": hornet}), encoding="utf-8"
    )
    (tmp_path / "AircraftAliases.json").write_text(
        json.dumps({"FA-18C_hornet": ["CommonData", "FA-18C_hornet"]}),
        encoding="utf-8",
    )
    return DcsBiosControlRegistry.from_path(tmp_path)


def set_control(
    registry: DcsBiosControlRegistry,
    state: DcsBiosState,
    module: str,
    identifier: str,
    value: int | str,
    *,
    timestamp: float,
) -> None:
    address, encoded = encode_control_value(registry, module, identifier, value)
    state.apply_write(address, encoded, received_at=timestamp)


def encode_control_value(
    registry: DcsBiosControlRegistry,
    module: str,
    identifier: str,
    value: int | str,
) -> tuple[int, bytes]:
    definition = registry.resolve(identifier, module=module)
    assert definition is not None
    if definition.output_type == "string":
        assert isinstance(value, str)
        encoded = value.encode("latin-1").ljust(definition.byte_length, b" ")
    else:
        assert isinstance(value, int)
        assert definition.shift is not None
        assert definition.mask is not None
        encoded = ((value << definition.shift) & definition.mask).to_bytes(2, "little")
    return definition.address, encoded
