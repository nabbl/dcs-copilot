from __future__ import annotations

import json
from pathlib import Path

from dcs_copilot.desktop.config_store import DesktopConfig


def test_desktop_config_round_trips_and_ignores_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"cloud_url": "wss://api.example/v1/realtime", "future": 1})
    )
    config = DesktopConfig.load(path)
    assert config.cloud_url == "wss://api.example/v1/realtime"
    assert config.device_id
    config.email = "pilot@example.com"
    assert config.save(path) == path
    loaded = DesktopConfig.load(path)
    assert loaded.email == "pilot@example.com"
    assert loaded.device_id == config.device_id
