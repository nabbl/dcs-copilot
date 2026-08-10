from __future__ import annotations

import json
from pathlib import Path

from dcs_copilot.dcs.bios_registry import DcsBiosControlRegistry
from dcs_copilot.dcs.bios_state import DcsBiosState


def test_resolves_root_and_decodes_generated_schema(bios_json_dir: Path) -> None:
    dcs_bios_root = bios_json_dir.parents[1]
    registry = DcsBiosControlRegistry.from_path(dcs_bios_root)
    state = DcsBiosState()
    state.apply_write(0, b"FA-18C_hornet\x00".ljust(24, b"\x00"))
    state.apply_write(0x7400, b"\x08\x00")

    aircraft = registry.resolve("_ACFT_NAME", module="MetadataStart")
    caution = registry.resolve("MASTER_CAUTION_LT", module="FA-18C_hornet")

    assert aircraft is not None
    assert caution is not None
    assert registry.decode(aircraft, state) == "FA-18C_hornet"
    assert registry.decode(caution, state) == 1
    assert registry.control_count == 3
    assert registry.module_count == 2
    assert registry.modules_for_aircraft("FA-18C_hornet") == ("FA-18C_hornet",)


def test_ambiguous_identifier_requires_module(tmp_path: Path) -> None:
    for module in ("A", "B"):
        document = {
            "Panel": {
                "SAME": {
                    "identifier": "SAME",
                    "outputs": [
                        {"type": "integer", "address": 10, "mask": 1, "shift_by": 0}
                    ],
                }
            }
        }
        (tmp_path / f"{module}.json").write_text(json.dumps(document))
    registry = DcsBiosControlRegistry.from_path(tmp_path)
    assert registry.resolve("SAME") is None
    assert registry.resolve("SAME", module="A") is not None


def test_supports_controls_wrapper_and_records_bad_files(tmp_path: Path) -> None:
    wrapped = {
        "Panel": {
            "controls": [
                {
                    "identifier": "VALUE",
                    "outputs": [
                        {"type": "integer", "address": 2, "mask": 0xFFFF, "shift_by": 0}
                    ],
                }
            ]
        }
    }
    (tmp_path / "Wrapped.json").write_text(json.dumps(wrapped))
    (tmp_path / "Broken.json").write_text("{")
    registry = DcsBiosControlRegistry.from_path(tmp_path)
    assert registry.resolve("VALUE", module="Wrapped") is not None
    assert len(registry.load_errors) == 1


def test_definitions_for_range_finds_overlapping_strings(bios_json_dir: Path) -> None:
    registry = DcsBiosControlRegistry.from_path(bios_json_dir)
    overlaps = registry.definitions_for_range(0x7414, 2)
    assert [item.identifier for item in overlaps] == ["UFC_SCRATCHPAD"]
