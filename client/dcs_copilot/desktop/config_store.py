"""Persistent, non-secret desktop configuration."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from dcs_copilot.config import Settings

APP_DIR_NAME = "MARA"
LEGACY_APP_DIR_NAME = "DCS Copilot"
CONFIG_FILE_NAME = "mara.json"
CONFIG_SCHEMA_VERSION = 2
LOCAL_BACKEND_URL = "ws://127.0.0.1:47100/v2/realtime"


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
    return LOCAL_BACKEND_URL


def realtime_url(value: str) -> str:
    """Normalize an HTTP base or WebSocket endpoint to MARA's realtime URL."""

    parsed = urlparse(value.strip())
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}.get(
        parsed.scheme.lower()
    )
    if scheme is None or not parsed.netloc:
        raise ValueError(
            "Backend URL must start with http://, https://, ws://, or wss://"
        )
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        path = "/v2/realtime"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def backend_http_url(value: str) -> str:
    parsed = urlparse(realtime_url(value))
    scheme = "https" if parsed.scheme == "wss" else "http"
    return urlunparse((scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA", "").strip()
        if root:
            return Path(root) / APP_DIR_NAME
    return Path.home() / ".dcs-copilot"


def legacy_app_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.getenv("LOCALAPPDATA", "").strip()
        if root:
            return Path(root) / LEGACY_APP_DIR_NAME
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
    schema_version: int = CONFIG_SCHEMA_VERSION
    backend_mode: str = "local"
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
    launch_at_login: bool = False

    @classmethod
    def load(cls, path: Path | None = None) -> DesktopConfig:
        config_path = path or app_data_dir() / "config" / CONFIG_FILE_NAME
        read_path = config_path
        if path is None and not read_path.is_file():
            legacy_candidates = (
                app_data_dir() / "config.json",
                legacy_app_data_dir() / "config.json",
            )
            for legacy in legacy_candidates:
                if legacy.is_file() and legacy != read_path:
                    read_path = legacy
                    break
        values: dict[str, object] = {}
        existed = read_path.is_file()
        if existed:
            try:
                document = json.loads(read_path.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    values = document
            except (OSError, ValueError, json.JSONDecodeError):
                values = {}
        defaults = cls()

        backend = values.get("backend")
        backend_values = backend if isinstance(backend, dict) else {}
        stored_url = backend_values.get("url")
        legacy_url = values.get("cloud_url")
        selected_url = (
            stored_url
            if isinstance(stored_url, str)
            else legacy_url
            if isinstance(legacy_url, str)
            else defaults.cloud_url
        )
        try:
            selected_url = realtime_url(selected_url)
        except ValueError:
            selected_url = defaults.cloud_url
        stored_mode = backend_values.get("mode")
        if isinstance(stored_mode, str) and stored_mode in {"local", "remote"}:
            backend_mode = stored_mode
        elif existed and isinstance(legacy_url, str) and legacy_url.strip():
            # Existing installations retain their hosted/custom endpoint.
            backend_mode = "remote"
        else:
            backend_mode = (
                "remote"
                if os.getenv("DCS_COPILOT_CLOUD_URL", "").strip()
                else defaults.backend_mode
            )

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
            schema_version=CONFIG_SCHEMA_VERSION,
            backend_mode=backend_mode,
            cloud_url=selected_url,
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
            assistant_mute_device_id=optional_int_value("assistant_mute_device_id"),
            assistant_mute_button=optional_int_value("assistant_mute_button"),
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
        config_path = path or app_data_dir() / "config" / CONFIG_FILE_NAME
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = config_path.with_suffix(".tmp")
        document = asdict(self)
        document.pop("schema_version", None)
        document.pop("backend_mode", None)
        document.pop("cloud_url", None)
        document = {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "backend": {
                "mode": self.backend_mode,
                "url": backend_http_url(self.cloud_url),
            },
            **document,
        }
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
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
        )

    def validate_backend(self) -> None:
        if self.backend_mode not in {"local", "remote"}:
            raise ValueError("Backend mode must be local or remote")
        self.cloud_url = realtime_url(self.cloud_url)
        parsed = urlparse(self.cloud_url)
        if self.backend_mode == "local" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("Local backend mode requires a loopback URL")
