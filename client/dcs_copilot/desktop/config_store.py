"""Persistent, non-secret desktop configuration."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from dcs_copilot.config import Settings
from dcs_copilot.events import SpeechMode

APP_DIR_NAME = "DCS Copilot"
CONFIG_FILE_NAME = "config.json"


def default_cloud_url() -> str:
    environment = os.getenv("DCS_COPILOT_CLOUD_URL", "").strip()
    if environment:
        return environment
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\DCS Copilot"
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "ServiceUrl")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except (FileNotFoundError, OSError):
            pass
    return "ws://127.0.0.1:8000/v1/realtime"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA", "").strip()
        if root:
            return Path(root) / APP_DIR_NAME
    return Path.home() / ".dcs-copilot"


def saved_games_dir() -> Path:
    """Resolve the Windows Saved Games known folder, including relocation."""

    if sys.platform == "win32":
        try:
            folder_id = ctypes.c_byte * 16
            # FOLDERID_SavedGames = {4C5C32FF-BB9D-43B0-BF7F-CFF5FBBDEB4D}
            saved_games_id = folder_id(
                0xFF,
                0x32,
                0x5C,
                0x4C,
                0x9D,
                0xBB,
                0xB0,
                0x43,
                0xBF,
                0x7F,
                0xCF,
                0xF5,
                0xFB,
                0xBD,
                0xEB,
                0x4D,
            )
            value = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(  # type: ignore[attr-defined]
                ctypes.byref(saved_games_id), 0, None, ctypes.byref(value)
            )
            if result == 0 and value.value:
                path = Path(value.value)
                ctypes.windll.ole32.CoTaskMemFree(value)  # type: ignore[attr-defined]
                return path
        except (AttributeError, OSError, ValueError):
            pass
    return Path.home() / "Saved Games"


def discover_dcs_folders() -> list[Path]:
    roots = [saved_games_dir()]
    one_drive = os.getenv("OneDrive", "").strip()
    if one_drive:
        roots.append(Path(one_drive) / "Saved Games")
    discovered: list[Path] = []
    for root in roots:
        for name in ("DCS", "DCS.openbeta", "DCS.openalpha"):
            candidate = root / name
            if candidate.is_dir() and candidate not in discovered:
                discovered.append(candidate.resolve())
    return discovered


def configure_launch_at_login(enabled: bool, executable: Path) -> None:
    """Configure a per-user Windows startup entry; no elevation is required."""

    if sys.platform != "win32":
        return
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_DIR_NAME, 0, winreg.REG_SZ, f'"{executable}"')
        else:
            try:
                winreg.DeleteValue(key, APP_DIR_NAME)
            except FileNotFoundError:
                pass


@dataclass(slots=True)
class DesktopConfig:
    cloud_url: str = field(default_factory=default_cloud_url)
    dcs_saved_games_path: str = ""
    email: str = ""
    device_id: str = ""
    ptt_key: str = "F13"
    ptt_device_id: int | None = None
    ptt_button: int | None = None
    assistant_mute_key: str = "F14"
    assistant_mute_device_id: int | None = None
    assistant_mute_button: int | None = None
    speech_mode: str = "NORMAL"
    launch_at_login: bool = False

    @classmethod
    def load(cls, path: Path | None = None) -> DesktopConfig:
        config_path = path or app_data_dir() / CONFIG_FILE_NAME
        values: dict[str, object] = {}
        if config_path.is_file():
            try:
                document = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    values = document
            except (OSError, ValueError, json.JSONDecodeError):
                values = {}
        defaults = cls()

        def text_value(name: str, default: str) -> str:
            value = values.get(name, default)
            return value if isinstance(value, str) else default

        launch_value = values.get("launch_at_login", defaults.launch_at_login)

        def optional_int_value(name: str) -> int | None:
            value = values.get(name)
            return (
                value
                if isinstance(value, int) and not isinstance(value, bool)
                else None
            )

        config = cls(
            cloud_url=text_value("cloud_url", defaults.cloud_url),
            dcs_saved_games_path=text_value(
                "dcs_saved_games_path", defaults.dcs_saved_games_path
            ),
            email=text_value("email", defaults.email),
            device_id=text_value("device_id", defaults.device_id),
            ptt_key=text_value("ptt_key", defaults.ptt_key),
            ptt_device_id=optional_int_value("ptt_device_id"),
            ptt_button=optional_int_value("ptt_button"),
            assistant_mute_key=text_value(
                "assistant_mute_key", defaults.assistant_mute_key
            ),
            assistant_mute_device_id=optional_int_value(
                "assistant_mute_device_id"
            ),
            assistant_mute_button=optional_int_value("assistant_mute_button"),
            speech_mode=text_value("speech_mode", defaults.speech_mode),
            launch_at_login=(
                launch_value
                if isinstance(launch_value, bool)
                else defaults.launch_at_login
            ),
        )
        if not config.device_id:
            config.device_id = str(uuid4())
        if not config.dcs_saved_games_path:
            candidates = discover_dcs_folders()
            if candidates:
                config.dcs_saved_games_path = str(candidates[0])
        return config

    def save(self, path: Path | None = None) -> Path:
        config_path = path or app_data_dir() / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = config_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(config_path)
        try:
            config_path.chmod(0o600)
        except OSError:
            pass
        return config_path

    @property
    def dcs_path(self) -> Path | None:
        value = self.dcs_saved_games_path.strip()
        return Path(value).expanduser() if value else None

    def runtime_settings(self, access_token: str) -> Settings:
        base = Settings.from_env()
        dcs_path = self.dcs_path
        bios_path = dcs_path / "Scripts" / "DCS-BIOS" if dcs_path else None
        return replace(
            base,
            dcs_bios_path=bios_path,
            cloud_url=self.cloud_url.strip(),
            access_token=access_token,
            device_id=self.device_id,
            copilot_ptt_key=self.ptt_key.strip().upper(),
            copilot_ptt_device=self.ptt_device_id,
            copilot_ptt_button=self.ptt_button,
            assistant_mute_key=self.assistant_mute_key.strip().upper(),
            assistant_mute_device=self.assistant_mute_device_id,
            assistant_mute_button=self.assistant_mute_button,
            speech_mode=SpeechMode(self.speech_mode.strip().upper()),
        )
