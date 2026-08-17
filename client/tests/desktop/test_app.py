from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dcs_copilot.backend import BackendError
from dcs_copilot.desktop.app import MainWindow
from dcs_copilot.desktop.config_store import DesktopConfig
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(
    qt_app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> MainWindow:
    config = DesktopConfig(
        cloud_url="ws://localhost:8000/v2/realtime", device_id="test-device"
    )
    monkeypatch.setattr(DesktopConfig, "load", classmethod(lambda cls: config))
    monkeypatch.setattr(
        DesktopConfig, "save", lambda self, path=None: tmp_path / "config.json"
    )
    monkeypatch.setattr(MainWindow, "_restore_session", lambda self: None)
    result = MainWindow()
    yield result
    result.close()


def test_failed_remote_switch_keeps_local_backend(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Manager:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    manager = Manager()
    window.backend_manager = manager  # type: ignore[assignment]
    window.dashboard.backend_mode.setCurrentIndex(
        window.dashboard.backend_mode.findData("remote")
    )
    window.dashboard.cloud_url.setText("https://unavailable.example")
    monkeypatch.setattr(
        "dcs_copilot.desktop.app.probe_backend",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BackendError("offline")),
    )

    with pytest.raises(BackendError, match="offline"):
        window._save_settings_silently()

    assert window.config.backend_mode == "local"
    assert window.config.cloud_url == "ws://localhost:8000/v2/realtime"
    assert not manager.stopped
