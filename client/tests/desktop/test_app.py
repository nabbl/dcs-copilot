from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dcs_copilot.desktop.app import SUPPORT_URL, MainWindow
from dcs_copilot.desktop.config_store import DesktopConfig
from PySide6.QtCore import QProcess
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


def test_support_link_is_visible_on_every_page(
    qt_app: QApplication, window: MainWindow
) -> None:
    window.show()
    qt_app.processEvents()
    assert window.support_link.isVisible()
    assert SUPPORT_URL in window.support_link.text()

    window.stack.setCurrentWidget(window.dashboard)
    qt_app.processEvents()
    assert window.support_link.isVisible()


def test_start_button_disables_before_process_finishes_starting(
    window: MainWindow,
) -> None:
    class PendingProcess:
        def __init__(self) -> None:
            self.starts: list[tuple[str, list[str]]] = []

        def state(self) -> QProcess.ProcessState:
            return QProcess.ProcessState.NotRunning

        def setProcessEnvironment(self, _environment: Any) -> None:
            pass

        def start(self, program: str, arguments: list[str]) -> None:
            self.starts.append((program, arguments))

    process = PendingProcess()
    window.process = process  # type: ignore[assignment]
    window._save_settings_silently = lambda: True  # type: ignore[method-assign]

    window.dashboard.run.click()

    assert not window.dashboard.run.isEnabled()
    assert window.dashboard.run.text() == "Starting MARA…"
    assert len(process.starts) == 1

    window.dashboard.run.click()
    assert len(process.starts) == 1
