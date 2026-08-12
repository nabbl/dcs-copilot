"""DCS-BIOS generated control-reference metadata loader."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .bios_state import DcsBiosState

ControlOutputType = Literal["integer", "string"]


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    identifier: str
    module: str
    output_type: ControlOutputType
    output_index: int
    address: int
    mask: int | None = None
    shift: int | None = None
    max_value: int | None = None
    string_length: int | None = None
    description: str = ""

    @property
    def byte_length(self) -> int:
        if self.output_type == "string":
            assert self.string_length is not None
            return self.string_length
        return 2

    @property
    def qualified_name(self) -> str:
        return (
            f"{self.module}/{self.identifier}/"
            f"{self.output_type}/{self.output_index}"
        )


class DcsBiosControlRegistry:
    """Index symbolic control outputs from generated DCS-BIOS JSON files."""

    def __init__(self, json_path: Path) -> None:
        self.json_path = json_path
        self._by_key: dict[tuple[str, str], list[ControlDefinition]] = defaultdict(list)
        self._by_identifier: dict[str, list[ControlDefinition]] = defaultdict(list)
        self._by_address: dict[int, set[ControlDefinition]] = defaultdict(set)
        self.aircraft_modules: dict[str, tuple[str, ...]] = {}
        self.load_errors: list[str] = []
        self.module_count = 0

    @property
    def control_count(self) -> int:
        return sum(len(items) for items in self._by_key.values())

    @classmethod
    def from_path(cls, path: Path) -> DcsBiosControlRegistry:
        json_path = cls.resolve_json_path(path)
        registry = cls(json_path)
        registry.load()
        return registry

    @staticmethod
    def resolve_json_path(path: Path) -> Path:
        path = path.expanduser()
        candidates = (
            path,
            path / "doc" / "json",
            path / "Scripts" / "DCS-BIOS" / "doc" / "json",
        )
        for candidate in candidates:
            if candidate.is_dir() and any(candidate.glob("*.json")):
                return candidate.resolve()
        raise FileNotFoundError(
            f"No generated DCS-BIOS JSON files found below {path}. "
            "Set DCS_BIOS_PATH to Scripts/DCS-BIOS or its doc/json directory."
        )

    @classmethod
    def discover(cls, configured: Path | None = None) -> Path | None:
        if configured is not None:
            return cls.resolve_json_path(configured)

        homes: list[Path] = [Path.home()]
        user_profile = os.getenv("USERPROFILE", "").strip()
        if user_profile:
            profile = Path(user_profile)
            if profile not in homes:
                homes.append(profile)

        installations = ("DCS", "DCS.openbeta", "DCS.openalpha")
        candidates: list[Path] = []
        for home in homes:
            for install in installations:
                candidates.append(
                    home
                    / "Saved Games"
                    / install
                    / "Scripts"
                    / "DCS-BIOS"
                    / "doc"
                    / "json"
                )
                candidates.append(
                    home
                    / "OneDrive"
                    / "Saved Games"
                    / install
                    / "Scripts"
                    / "DCS-BIOS"
                    / "doc"
                    / "json"
                )
        for candidate in candidates:
            if candidate.is_dir() and any(candidate.glob("*.json")):
                return candidate.resolve()
        return None

    def load(self) -> None:
        self._by_key.clear()
        self._by_identifier.clear()
        self._by_address.clear()
        self.aircraft_modules.clear()
        self.load_errors.clear()
        loaded_modules: set[str] = set()
        for file_path in sorted(self.json_path.glob("*.json")):
            if file_path.name == "AircraftAliases.json":
                self._load_aliases(file_path)
                continue
            try:
                document = json.loads(file_path.read_text(encoding="utf-8-sig"))
                definitions = list(self._parse_module(file_path.stem, document))
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.load_errors.append(f"{file_path.name}: {exc}")
                continue
            if definitions:
                loaded_modules.add(file_path.stem)
            for definition in definitions:
                key = (definition.module, definition.identifier)
                self._by_key[key].append(definition)
                self._by_identifier[definition.identifier].append(definition)
                for address in range(
                    definition.address, definition.address + definition.byte_length
                ):
                    self._by_address[address].add(definition)
        self.module_count = len(loaded_modules)

    def _load_aliases(self, file_path: Path) -> None:
        try:
            document = json.loads(file_path.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict):
                raise TypeError("alias document must be a JSON object")
            for aircraft, modules in document.items():
                if (
                    isinstance(aircraft, str)
                    and isinstance(modules, list)
                    and all(isinstance(module, str) for module in modules)
                ):
                    self.aircraft_modules[aircraft] = tuple(modules)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self.load_errors.append(f"{file_path.name}: {exc}")

    def _parse_module(
        self, module: str, document: object
    ) -> Iterator[ControlDefinition]:
        if not isinstance(document, dict):
            raise TypeError("module document must be a JSON object")
        for category in document.values():
            controls: object = category
            if isinstance(category, dict) and "controls" in category:
                controls = category["controls"]
            if isinstance(controls, dict):
                entries: Iterable[object] = controls.values()
            elif isinstance(controls, list):
                entries = controls
            else:
                continue
            for control in entries:
                if not isinstance(control, dict):
                    continue
                identifier = control.get("identifier")
                outputs = control.get("outputs", [])
                if not isinstance(identifier, str) or not isinstance(outputs, list):
                    continue
                for output_index, output in enumerate(outputs):
                    if not isinstance(output, dict):
                        continue
                    output_type = output.get("type")
                    address = output.get("address")
                    if output_type not in ("integer", "string") or not isinstance(
                        address, int
                    ):
                        continue
                    description = str(
                        output.get("description") or control.get("description") or ""
                    )
                    if output_type == "integer":
                        mask = output.get("mask", 0xFFFF)
                        shift = output.get("shift_by", 0)
                        max_value = output.get("max_value")
                        if (
                            max_value is None
                            and isinstance(mask, int)
                            and isinstance(shift, int)
                        ):
                            max_value = mask >> shift
                        if (
                            not isinstance(mask, int)
                            or not isinstance(shift, int)
                            or not isinstance(max_value, int)
                        ):
                            continue
                        yield ControlDefinition(
                            identifier,
                            module,
                            "integer",
                            output_index,
                            address,
                            mask,
                            shift,
                            max_value,
                            None,
                            description,
                        )
                    else:
                        length = output.get("max_length")
                        if not isinstance(length, int) or length <= 0:
                            continue
                        yield ControlDefinition(
                            identifier,
                            module,
                            "string",
                            output_index,
                            address,
                            None,
                            None,
                            None,
                            length,
                            description,
                        )

    def resolve(
        self,
        identifier: str,
        *,
        module: str | None = None,
        output_type: ControlOutputType | None = None,
    ) -> ControlDefinition | None:
        candidates = (
            self._by_key.get((module, identifier), [])
            if module
            else self._by_identifier.get(identifier, [])
        )
        filtered = [
            item
            for item in candidates
            if output_type is None or item.output_type == output_type
        ]
        if not filtered:
            return None
        if module is None and len({item.module for item in filtered}) > 1:
            return None
        return filtered[0]

    def definitions_for_range(
        self, address: int, length: int
    ) -> tuple[ControlDefinition, ...]:
        result: set[ControlDefinition] = set()
        for current in range(address, address + length):
            result.update(self._by_address.get(current, ()))
        return tuple(result)

    def modules_for_aircraft(self, aircraft: str) -> tuple[str, ...]:
        aircraft_modules = self.aircraft_modules.get(aircraft, (aircraft,))
        return tuple(dict.fromkeys((*aircraft_modules, "CommonData")))

    def definitions(self, module: str | None = None) -> tuple[ControlDefinition, ...]:
        result = [item for values in self._by_key.values() for item in values]
        if module is not None:
            result = [item for item in result if item.module == module]
        return tuple(result)

    @staticmethod
    def decode(definition: ControlDefinition, state: DcsBiosState) -> int | str | None:
        raw = state.read(definition.address, definition.byte_length)
        if raw is None:
            return None
        if definition.output_type == "string":
            return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").rstrip()
        word = int.from_bytes(raw, "little")
        assert definition.mask is not None
        assert definition.shift is not None
        return (word & definition.mask) >> definition.shift
