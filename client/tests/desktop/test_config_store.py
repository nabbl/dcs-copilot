from __future__ import annotations

import json
from pathlib import Path

from dcs_copilot.desktop.config_store import DesktopConfig


def test_desktop_config_round_trips_and_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"cloud_url": "wss://api.example/v2/realtime", "future": 1})
    )
    config = DesktopConfig.load(path)
    assert config.cloud_url == "wss://api.example/v2/realtime"
    assert config.device_id
    config.email = "pilot@example.com"
    config.ptt_device_id = 2
    config.ptt_button = 5
    config.assistant_mute_key = "F16"
    config.assistant_mute_device_id = 3
    config.assistant_mute_button = 7
    assert config.save(path) == path
    loaded = DesktopConfig.load(path)
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
