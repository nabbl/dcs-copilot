"""Non-capturing PortAudio device inspection for diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    input_channels: int
    output_channels: int


@dataclass(frozen=True, slots=True)
class AudioDeviceStatus:
    input_detail: str
    output_detail: str
    ready: bool


def discover_audio_devices() -> list[AudioDevice]:
    """List PortAudio devices without opening a capture or playback stream."""

    try:
        import pyaudio  # type: ignore[import-untyped]
    except ImportError:
        return []
    try:
        audio = pyaudio.PyAudio()
    except OSError:
        return []
    try:
        devices: list[AudioDevice] = []
        for index in range(audio.get_device_count()):
            try:
                info: dict[str, Any] = audio.get_device_info_by_index(index)
            except (OSError, ValueError):
                continue
            input_channels = int(info.get("maxInputChannels", 0) or 0)
            output_channels = int(info.get("maxOutputChannels", 0) or 0)
            if input_channels <= 0 and output_channels <= 0:
                continue
            devices.append(
                AudioDevice(
                    index=index,
                    name=str(info.get("name") or f"Audio device {index}"),
                    input_channels=input_channels,
                    output_channels=output_channels,
                )
            )
        return devices
    except (OSError, ValueError):
        return []
    finally:
        audio.terminate()


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
