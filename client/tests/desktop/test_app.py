from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dcs_copilot.backend import BackendError, BackendInfo, ServiceInfo
from dcs_copilot.desktop.app import SUPPORT_URL, MainWindow
from dcs_copilot.desktop.config_store import LOCAL_BACKEND_URL, DesktopConfig
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
    window.dashboard._backend_operational = True
    window.dashboard.run.setEnabled(True)

    window.dashboard.run.click()

    assert not window.dashboard.run.isEnabled()
    assert window.dashboard.run.text() == "Starting MARA…"
    assert len(process.starts) == 1

    window.dashboard.run.click()
    assert len(process.starts) == 1


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
    assert window.config.cloud_url == LOCAL_BACKEND_URL
    assert not manager.stopped


def test_local_backend_url_is_fixed_and_remote_url_is_editable(
    window: MainWindow,
) -> None:
    dashboard = window.dashboard

    dashboard.backend_mode.setCurrentIndex(dashboard.backend_mode.findData("local"))
    assert dashboard.cloud_url.text() == LOCAL_BACKEND_URL
    assert not dashboard.cloud_url.isEnabled()

    dashboard.backend_mode.setCurrentIndex(dashboard.backend_mode.findData("remote"))
    assert dashboard.cloud_url.isEnabled()


def test_settings_are_on_a_dedicated_cog_screen(window: MainWindow) -> None:
    dashboard = window.dashboard
    assert dashboard.content.currentWidget() is dashboard.main_tabs
    assert [
        dashboard.main_tabs.tabText(index)
        for index in range(dashboard.main_tabs.count())
    ] == ["Overview", "Activity"]
    assert dashboard.settings_button.toolTip() == "Settings"

    dashboard.settings_button.click()

    assert dashboard.content.currentWidget() is dashboard.settings_page
    assert not dashboard.settings_button.isEnabled()

    dashboard.show_dashboard()

    assert dashboard.content.currentWidget() is dashboard.main_tabs
    assert dashboard.settings_button.isEnabled()


def test_settings_explain_kokoro_and_openai_readiness(window: MainWindow) -> None:
    info = BackendInfo(
        url="http://127.0.0.1:47100",
        mara_version="0.1.0",
        api_version="1",
        deployment="local",
        capabilities={"kokoro": True},
        openai_configured=False,
        latency_ms=4.0,
        operational=False,
        blocking_reasons=("Add an OpenAI API key in MARA settings.",),
        services={
            "kokoro": ServiceInfo("ready", "Downloaded and verified.", 100),
            "openai": ServiceInfo("missing", "Add an API key."),
        },
    )

    window.dashboard.set_backend_info(info, owned=True)

    assert window.dashboard.backend_diagnostic_card.value.text() == "Running"
    assert window.dashboard.kokoro_diagnostic_card.value.text() == "Ready"
    assert window.dashboard.openai_diagnostic_card.value.text() == "API key needed"
    assert window.dashboard.backend_card.value.text() == "Setup required"
    assert not window.dashboard.run.isEnabled()
