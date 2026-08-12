"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

def _load_dotenv(path: Path) -> None:
    """Load a small, dependency-free subset of dotenv syntax."""

    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True, slots=True)
class Settings:
    dcs_bios_path: Path | None = None
    multicast_group: str = "239.255.50.10"
    port: int = 5010
    interface: str = "127.0.0.1"
    stale_timeout: float = 2.0
    cloud_url: str = "ws://127.0.0.1:8000/v2/realtime"
    access_token: str = field(default="local-dev-token", repr=False)
    device_id: str = "local-development-device"
    copilot_ptt_key: str = "F13"
    copilot_ptt_device: int | None = None
    copilot_ptt_button: int | None = None
    assistant_mute_key: str = "F14"
    assistant_mute_device: int | None = None
    assistant_mute_button: int | None = None
    audio_input_device: int | None = None
    audio_output_device: int | None = None
    audio_sample_rate: int = 16_000
    audio_output_sample_rate: int = 24_000
    audio_channels: int = 1
    audio_chunk_ms: int = 20
    audio_queue_size: int = 256
    cloud_handshake_timeout_seconds: float = 5.0
    cloud_reconnect_max_seconds: float = 10.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> Settings:
        _load_dotenv(dotenv_path or Path.cwd() / ".env")
        configured_path = os.getenv("DCS_BIOS_PATH", "").strip()
        return cls(
            dcs_bios_path=Path(configured_path).expanduser()
            if configured_path
            else None,
            multicast_group=os.getenv("DCS_BIOS_MULTICAST_GROUP", "239.255.50.10"),
            port=int(os.getenv("DCS_BIOS_PORT", "5010")),
            interface=os.getenv("DCS_BIOS_INTERFACE", "127.0.0.1"),
            stale_timeout=float(os.getenv("DCS_BIOS_STALE_TIMEOUT", "2.0")),
            cloud_url=os.getenv(
                "DCS_COPILOT_CLOUD_URL",
                "ws://127.0.0.1:8000/v2/realtime",
            ).strip(),
            access_token=os.getenv("DCS_COPILOT_ACCESS_TOKEN", "local-dev-token"),
            device_id=os.getenv(
                "DCS_COPILOT_DEVICE_ID", "local-development-device"
            ).strip(),
            copilot_ptt_key=os.getenv("COPILOT_PTT_KEY", "F13").strip().upper(),
            copilot_ptt_device=_optional_int("COPILOT_PTT_DEVICE"),
            copilot_ptt_button=_optional_int("COPILOT_PTT_BUTTON"),
            assistant_mute_key=os.getenv("COPILOT_MUTE_KEY", "F14").strip().upper(),
            assistant_mute_device=_optional_int("COPILOT_MUTE_DEVICE"),
            assistant_mute_button=_optional_int("COPILOT_MUTE_BUTTON"),
            audio_input_device=_optional_int("AUDIO_INPUT_DEVICE"),
            audio_output_device=_optional_int("AUDIO_OUTPUT_DEVICE"),
            audio_sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "16000")),
            audio_output_sample_rate=int(
                os.getenv("AUDIO_OUTPUT_SAMPLE_RATE", "24000")
            ),
            audio_channels=int(os.getenv("AUDIO_CHANNELS", "1")),
            audio_chunk_ms=int(os.getenv("AUDIO_CHUNK_MS", "20")),
            audio_queue_size=int(os.getenv("AUDIO_QUEUE_SIZE", "256")),
            cloud_handshake_timeout_seconds=float(
                os.getenv("CLOUD_HANDSHAKE_TIMEOUT_SECONDS", "5")
            ),
            cloud_reconnect_max_seconds=float(
                os.getenv("CLOUD_RECONNECT_MAX_SECONDS", "10")
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
