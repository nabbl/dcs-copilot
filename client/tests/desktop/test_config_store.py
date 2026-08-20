from __future__ import annotations

import json
from pathlib import Path

import pytest
from dcs_copilot.desktop.config_store import DesktopConfig


def test_desktop_config_round_trips_and_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"cloud_url": "wss://api.example/v2/realtime", "future": 1})
    )
    config = DesktopConfig.load(path)
    assert config.cloud_url == "wss://api.example/v2/realtime"
    assert config.backend_mode == "remote"
    assert config.device_id
    config.email = "pilot@example.com"
    config.ptt_device_id = 2
    config.ptt_button = 5
    config.assistant_mute_key = "F16"
    config.assistant_mute_device_id = 3
    config.assistant_mute_button = 7
    assert config.save(path) == path
    loaded = DesktopConfig.load(path)
    document = json.loads(path.read_text())
    assert document["schema_version"] == 2
    assert document["backend"] == {
        "mode": "remote",
        "url": "https://api.example",
    }
    assert loaded.email == "pilot@example.com"
    assert loaded.device_id == config.device_id
    assert loaded.ptt_device_id == 2
    assert loaded.ptt_button == 5
    assert loaded.assistant_mute_key == "F16"
    assert loaded.assistant_mute_device_id == 3
    assert loaded.assistant_mute_button == 7
    runtime = loaded.runtime_settings("access-token")
    assert runtime.assistant_mute_device == 3
    assert runtime.assistant_mute_button == 7


def test_fresh_config_defaults_to_managed_loopback(tmp_path: Path) -> None:
    config = DesktopConfig.load(tmp_path / "missing.json")
    assert config.backend_mode == "local"
    assert config.cloud_url == "ws://127.0.0.1:47100/v2/realtime"


def test_local_openai_secret_is_never_serialized(tmp_path: Path) -> None:
    from dcs_copilot.desktop.backend_credentials import MemoryBackendCredentialStore

    store = MemoryBackendCredentialStore()
    store.set_openai_key("sk-super-secret")
    path = DesktopConfig().save(tmp_path / "config.json")
    assert "sk-super-secret" not in path.read_text()
    assert store.get_openai_key() == "sk-super-secret"
    store.delete_openai_key()
    assert store.get_openai_key() is None


def test_backend_validation_rejects_invalid_remote_url_and_fixes_local_url() -> None:
    config = DesktopConfig(backend_mode="remote", cloud_url="not-a-url")
    with pytest.raises(ValueError, match="Backend URL"):
        config.validate_backend()
    config = DesktopConfig(backend_mode="local", cloud_url="http://192.168.1.50:47100")
    config.validate_backend()
    assert config.cloud_url == "ws://127.0.0.1:47100/v2/realtime"


def test_stored_local_backend_ignores_custom_url(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "backend": {
                    "mode": "local",
                    "url": "http://localhost:9999",
                }
            }
        )
    )

    config = DesktopConfig.load(path)

    assert config.cloud_url == "ws://127.0.0.1:47100/v2/realtime"
