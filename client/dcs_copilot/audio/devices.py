"""Non-capturing PortAudio device inspection for diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioDeviceStatus:
    input_detail: str
    output_detail: str
    ready: bool


def inspect_audio_devices(
    input_index: int | None, output_index: int | None
) -> AudioDeviceStatus:
    try:
        import pyaudio  # type: ignore[import-untyped]
    except ImportError:
        return AudioDeviceStatus("PyAudio missing", "PyAudio missing", False)
    try:
        audio = pyaudio.PyAudio()
    except OSError as exc:
        detail = f"unavailable ({exc})"
        return AudioDeviceStatus(detail, detail, False)
    try:
        input_info: dict[str, Any] = (
            audio.get_default_input_device_info()
            if input_index is None
            else audio.get_device_info_by_index(input_index)
        )
        output_info: dict[str, Any] = (
            audio.get_default_output_device_info()
            if output_index is None
            else audio.get_device_info_by_index(output_index)
        )
        input_name = str(input_info.get("name", input_index or "default"))
        output_name = str(output_info.get("name", output_index or "default"))
        return AudioDeviceStatus(input_name, output_name, True)
    except (OSError, ValueError) as exc:
        detail = f"unavailable ({exc})"
        return AudioDeviceStatus(detail, detail, False)
    finally:
        audio.terminate()
