"""Qt desktop shell for account, DCS setup, settings, and runtime control."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import (  # type: ignore[import-untyped]
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPalette  # type: ignore[import-untyped]
from PySide6.QtWidgets import (  # type: ignore[import-untyped]
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dcs_copilot.cli.run import run_client
from dcs_copilot.input.ptt import (
    JoystickButtonSelection,
    JoystickDevice,
    detect_joystick_button,
    discover_joysticks,
)
from dcs_copilot.logging import configure_logging

from .activity import ActivityOutputFilter
from .auth import AuthError, StoredAuthSession, TokenPair
from .config_store import DesktopConfig, configure_launch_at_login
from .dcs_setup import inspect_installation, install_dcs_bios

APP_NAME = "DCS Copilot"
ACCENT = "#34d399"
DARK = "#0b1220"
PANEL = "#111c2f"
MUTED = "#8ea0b8"


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, action: Callable[[], Any]) -> None:
        super().__init__()
        self.action = action
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.action()
        except Exception as exc:  # noqa: BLE001 - boundary reports background failures
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)


class StatusCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.title.setObjectName("eyebrow")
        self.value = QLabel("Checking…")
        self.value.setObjectName("statusValue")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_status(self, value: str, detail: str, *, good: bool) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {ACCENT if good else '#fbbf24'}")
        self.detail.setText(detail)


class LoginPage(QWidget):
    submitted = Signal(str, str, bool)

    def __init__(self) -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(64, 48, 64, 48)
        brand = QVBoxLayout()
        mark = QLabel("DCS // COPILOT")
        mark.setObjectName("brand")
        heading = QLabel("MARA")
        heading.setObjectName("hero")
        copy = QLabel(
            "Mission-Aware Realtime Assistant\n\n"
            "Real-time cockpit awareness, concise voice guidance, and habits "
            "that improve with every flight."
        )
        copy.setObjectName("muted")
        copy.setWordWrap(True)
        copy.setMaximumWidth(430)
        brand.addStretch()
        brand.addWidget(mark)
        brand.addSpacing(24)
        brand.addWidget(heading)
        brand.addSpacing(16)
        brand.addWidget(copy)
        brand.addStretch()

        card = QFrame()
        card.setObjectName("loginCard")
        card.setMaximumWidth(430)
        form = QVBoxLayout(card)
        form.setContentsMargins(36, 36, 36, 36)
        title = QLabel("Welcome back")
        title.setObjectName("sectionTitle")
        self.subtitle = QLabel("Sign in to connect this PC to DCS Copilot.")
        self.subtitle.setObjectName("muted")
        self.email = QLineEdit()
        self.email.setPlaceholderText("pilot@example.com")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._submit)
        self.submit = QPushButton("Sign in")
        self.submit.setObjectName("primary")
        self.submit.clicked.connect(self._submit)
        self.toggle = QPushButton("New pilot? Create an account")
        self.toggle.setObjectName("link")
        self.toggle.clicked.connect(self._toggle_mode)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self._register = False
        form.addWidget(title)
        form.addWidget(self.subtitle)
        form.addSpacing(18)
        form.addWidget(QLabel("EMAIL"))
        form.addWidget(self.email)
        form.addWidget(QLabel("PASSWORD"))
        form.addWidget(self.password)
        form.addSpacing(8)
        form.addWidget(self.submit)
        form.addWidget(self.toggle)
        form.addWidget(self.error)
        form.addStretch()
        outer.addLayout(brand, 3)
        outer.addWidget(card, 2)

    def _toggle_mode(self) -> None:
        self._register = not self._register
        self.submit.setText("Create account" if self._register else "Sign in")
        self.toggle.setText(
            "Already have an account? Sign in"
            if self._register
            else "New pilot? Create an account"
        )
        self.subtitle.setText(
            "Create an account with a password of at least 10 characters."
            if self._register
            else "Sign in to connect this PC to DCS Copilot."
        )
        self.error.clear()

    def _submit(self) -> None:
        self.error.clear()
        self.submit.setEnabled(False)
        self.submitted.emit(
            self.email.text().strip(), self.password.text(), self._register
        )

    def finish(self, error: str | None = None) -> None:
        self.submit.setEnabled(True)
        self.password.clear()
        self.error.setText(error or "")


class DashboardPage(QWidget):
    install_requested = Signal()
    save_requested = Signal()
    run_requested = Signal()
    stop_requested = Signal()
    logout_requested = Signal()
    learn_ptt_requested = Signal()
    learn_mute_requested = Signal()

    def __init__(self, config: DesktopConfig) -> None:
        super().__init__()
        self.config = config
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 28)
        header = QHBoxLayout()
        brand = QLabel("MARA // DCS COPILOT")
        brand.setObjectName("brand")
        self.account = QLabel("")
        self.account.setObjectName("muted")
        logout = QPushButton("Sign out")
        logout.setObjectName("link")
        logout.clicked.connect(self.logout_requested)
        header.addWidget(brand)
        header.addStretch()
        header.addWidget(self.account)
        header.addWidget(logout)
        outer.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._home_tab(), "Overview")
        tabs.addTab(self._settings_tab(), "Settings")
        tabs.addTab(self._logs_tab(), "Activity")
        outer.addWidget(tabs)

    def _home_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 28, 8, 8)
        title = QLabel("MARA")
        title.setObjectName("heroSmall")
        subtitle = QLabel(
            "Mission-Aware Realtime Assistant — complete the checks below, "
            "then launch MARA before entering the cockpit."
        )
        subtitle.setObjectName("muted")
        cards = QHBoxLayout()
        self.account_card = StatusCard("Account")
        self.dcs_card = StatusCard("DCS-BIOS")
        self.runtime_card = StatusCard("MARA")
        cards.addWidget(self.account_card)
        cards.addWidget(self.dcs_card)
        cards.addWidget(self.runtime_card)
        actions = QHBoxLayout()
        self.install = QPushButton("Install / repair DCS-BIOS")
        self.install.clicked.connect(self.install_requested)
        self.run = QPushButton("Start MARA")
        self.run.setObjectName("primary")
        self.run.clicked.connect(self.run_requested)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(self.stop_requested)
        self.stop.setEnabled(False)
        actions.addWidget(self.install)
        actions.addStretch()
        actions.addWidget(self.stop)
        actions.addWidget(self.run)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(22)
        layout.addLayout(cards)
        layout.addSpacing(18)
        layout.addLayout(actions)
        layout.addStretch()
        return tab

    def _settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 28, 8, 8)
        title = QLabel("Client settings")
        title.setObjectName("sectionTitle")
        form = QFormLayout()
        path_row = QHBoxLayout()
        self.dcs_path = QLineEdit(self.config.dcs_saved_games_path)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.dcs_path)
        path_row.addWidget(browse)
        self.cloud_url = QLineEdit(self.config.cloud_url)
        ptt_device_row = QHBoxLayout()
        self.ptt_device = QComboBox()
        self.ptt_control = QComboBox()
        refresh_ptt = QPushButton("Refresh")
        refresh_ptt.clicked.connect(self._refresh_ptt_devices)
        self.learn_ptt = QPushButton("Detect button…")
        self.learn_ptt.clicked.connect(self.learn_ptt_requested)
        ptt_device_row.addWidget(self.ptt_device)
        ptt_device_row.addWidget(refresh_ptt)
        ptt_device_row.addWidget(self.learn_ptt)
        self.ptt_hint = QLabel("Tip: click Detect button, then press your HOTAS/PTT button.")
        self.ptt_hint.setObjectName("muted")
        self.ptt_hint.setWordWrap(True)
        self._ptt_devices: dict[int, JoystickDevice] = {}
        self._refresh_ptt_devices()
        self.ptt_device.currentIndexChanged.connect(self._update_ptt_controls)
        mute_device_row = QHBoxLayout()
        self.mute_device = QComboBox()
        self.mute_control = QComboBox()
        refresh_mute = QPushButton("Refresh")
        refresh_mute.clicked.connect(self._refresh_mute_devices)
        self.learn_mute = QPushButton("Detect button…")
        self.learn_mute.clicked.connect(self.learn_mute_requested)
        mute_device_row.addWidget(self.mute_device)
        mute_device_row.addWidget(refresh_mute)
        mute_device_row.addWidget(self.learn_mute)
        self.mute_hint = QLabel(
            "Tip: click Detect button, then press your HOTAS MARA mute button."
        )
        self.mute_hint.setObjectName("muted")
        self.mute_hint.setWordWrap(True)
        self._mute_devices: dict[int, JoystickDevice] = {}
        self._refresh_mute_devices()
        self.mute_device.currentIndexChanged.connect(self._update_mute_controls)
        self.speech = QComboBox()
        self.speech.addItems(["MINIMAL", "NORMAL", "COACH"])
        self.speech.setCurrentText(self.config.speech_mode)
        self.launch_login = QCheckBox("Start DCS Copilot when I sign in to Windows")
        self.launch_login.setChecked(self.config.launch_at_login)
        form.addRow("DCS Saved Games folder", path_row)
        form.addRow("Service URL", self.cloud_url)
        form.addRow("PTT input device", ptt_device_row)
        form.addRow("PTT key / button", self.ptt_control)
        form.addRow("", self.ptt_hint)
        form.addRow("MARA mute input device", mute_device_row)
        form.addRow("MARA mute key / button", self.mute_control)
        form.addRow("", self.mute_hint)
        form.addRow("Speech mode", self.speech)
        form.addRow("", self.launch_login)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save_requested)
        layout.addWidget(title)
        layout.addSpacing(18)
        layout.addLayout(form)
        layout.addSpacing(18)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        return tab

    def _logs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 28, 8, 8)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText("Pilot and MARA activity will appear here.")
        layout.addWidget(self.logs)
        return tab

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select DCS Saved Games folder",
            self.dcs_path.text() or str(Path.home()),
        )
        if selected:
            self.dcs_path.setText(selected)

    def _refresh_ptt_devices(self) -> None:
        selected = (
            self.ptt_device.currentData()
            if self.ptt_device.count()
            else self.config.ptt_device_id
        )
        devices = discover_joysticks()
        self._ptt_devices = {device.device_id: device for device in devices}
        self.ptt_device.blockSignals(True)
        self.ptt_device.clear()
        self.ptt_device.addItem("Keyboard", None)
        for device in devices:
            self.ptt_device.addItem(
                f"{device.name} ({device.button_count} buttons)", device.device_id
            )
        if selected is not None and selected not in self._ptt_devices:
            self.ptt_device.addItem(f"Controller {selected} (not connected)", selected)
        index = self.ptt_device.findData(selected)
        self.ptt_device.setCurrentIndex(max(0, index))
        self.ptt_device.blockSignals(False)
        self._update_ptt_controls()

    def _update_ptt_controls(self) -> None:
        selected_control = (
            self.ptt_control.currentData()
            if self.ptt_control.count()
            else (
                self.config.ptt_key
                if self.config.ptt_device_id is None
                else self.config.ptt_button
            )
        )
        device_id = self.ptt_device.currentData()
        self.ptt_control.clear()
        desired: object
        if device_id is None:
            for number in range(1, 25):
                key = f"F{number}"
                self.ptt_control.addItem(key, key)
            desired = (
                selected_control
                if isinstance(selected_control, str)
                else self.config.ptt_key
            )
        else:
            device = self._ptt_devices.get(device_id)
            button_count = (
                device.button_count if device else max(self.config.ptt_button or 1, 1)
            )
            for button in range(1, min(button_count, 32) + 1):
                self.ptt_control.addItem(f"Button {button}", button)
            desired = (
                selected_control
                if isinstance(selected_control, int)
                else self.config.ptt_button
            )
        index = self.ptt_control.findData(desired)
        self.ptt_control.setCurrentIndex(max(0, index))

    def begin_ptt_learning(self) -> None:
        self.learn_ptt.setEnabled(False)
        self.ptt_hint.setText("Listening for a joystick/HOTAS button press…")

    def finish_ptt_learning(
        self, selection: JoystickButtonSelection | None = None, error: str | None = None
    ) -> None:
        self.learn_ptt.setEnabled(True)
        if selection is None:
            self.ptt_hint.setText(error or "No joystick/HOTAS button was detected.")
            return
        self._ptt_devices[selection.device.device_id] = selection.device
        if self.ptt_device.findData(selection.device.device_id) < 0:
            self.ptt_device.addItem(
                f"{selection.device.name} ({selection.device.button_count} buttons)",
                selection.device.device_id,
            )
        self.ptt_device.setCurrentIndex(
            max(0, self.ptt_device.findData(selection.device.device_id))
        )
        self._update_ptt_controls()
        self.ptt_control.setCurrentIndex(max(0, self.ptt_control.findData(selection.button)))
        self.ptt_hint.setText(
            f"Detected {selection.device.name}, button {selection.button}."
        )

    def _refresh_mute_devices(self) -> None:
        selected = (
            self.mute_device.currentData()
            if self.mute_device.count()
            else self.config.assistant_mute_device_id
        )
        devices = discover_joysticks()
        self._mute_devices = {device.device_id: device for device in devices}
        self.mute_device.blockSignals(True)
        self.mute_device.clear()
        self.mute_device.addItem("Keyboard", None)
        for device in devices:
            self.mute_device.addItem(
                f"{device.name} ({device.button_count} buttons)", device.device_id
            )
        if selected is not None and selected not in self._mute_devices:
            self.mute_device.addItem(f"Controller {selected} (not connected)", selected)
        index = self.mute_device.findData(selected)
        self.mute_device.setCurrentIndex(max(0, index))
        self.mute_device.blockSignals(False)
        self._update_mute_controls()

    def _update_mute_controls(self) -> None:
        selected_control = (
            self.mute_control.currentData()
            if self.mute_control.count()
            else (
                self.config.assistant_mute_key
                if self.config.assistant_mute_device_id is None
                else self.config.assistant_mute_button
            )
        )
        device_id = self.mute_device.currentData()
        self.mute_control.clear()
        desired: object
        if device_id is None:
            for number in range(1, 25):
                key = f"F{number}"
                self.mute_control.addItem(key, key)
            desired = (
                selected_control
                if isinstance(selected_control, str)
                else self.config.assistant_mute_key
            )
        else:
            device = self._mute_devices.get(device_id)
            button_count = (
                device.button_count
                if device
                else max(self.config.assistant_mute_button or 1, 1)
            )
            for button in range(1, min(button_count, 32) + 1):
                self.mute_control.addItem(f"Button {button}", button)
            desired = (
                selected_control
                if isinstance(selected_control, int)
                else self.config.assistant_mute_button
            )
        index = self.mute_control.findData(desired)
        self.mute_control.setCurrentIndex(max(0, index))

    def begin_mute_learning(self) -> None:
        self.learn_mute.setEnabled(False)
        self.mute_hint.setText("Listening for a joystick/HOTAS button press…")

    def finish_mute_learning(
        self, selection: JoystickButtonSelection | None = None, error: str | None = None
    ) -> None:
        self.learn_mute.setEnabled(True)
        if selection is None:
            self.mute_hint.setText(error or "No joystick/HOTAS button was detected.")
            return
        self._mute_devices[selection.device.device_id] = selection.device
        if self.mute_device.findData(selection.device.device_id) < 0:
            self.mute_device.addItem(
                f"{selection.device.name} ({selection.device.button_count} buttons)",
                selection.device.device_id,
            )
        self.mute_device.setCurrentIndex(
            max(0, self.mute_device.findData(selection.device.device_id))
        )
        self._update_mute_controls()
        self.mute_control.setCurrentIndex(
            max(0, self.mute_control.findData(selection.button))
        )
        self.mute_hint.setText(
            f"Detected {selection.device.name}, button {selection.button}."
        )

    def update_config(self) -> None:
        self.config.dcs_saved_games_path = self.dcs_path.text().strip()
        self.config.cloud_url = self.cloud_url.text().strip()
        device_id = self.ptt_device.currentData()
        self.config.ptt_device_id = device_id
        if device_id is None:
            self.config.ptt_key = str(self.ptt_control.currentData())
            self.config.ptt_button = None
        else:
            self.config.ptt_button = int(self.ptt_control.currentData())
        mute_device_id = self.mute_device.currentData()
        self.config.assistant_mute_device_id = mute_device_id
        if mute_device_id is None:
            self.config.assistant_mute_key = str(self.mute_control.currentData())
            self.config.assistant_mute_button = None
        else:
            self.config.assistant_mute_button = int(self.mute_control.currentData())
        if (
            device_id is None
            and mute_device_id is None
            and self.config.ptt_key == self.config.assistant_mute_key
        ):
            raise ValueError("Mute / unmute key cannot be the same as keyboard PTT.")
        if (
            device_id is not None
            and device_id == mute_device_id
            and self.config.ptt_button == self.config.assistant_mute_button
        ):
            raise ValueError("Mute / unmute button cannot be the same as PTT.")
        self.config.speech_mode = self.speech.currentText()
        self.config.launch_at_login = self.launch_login.isChecked()

    def refresh_setup_status(self) -> None:
        path = self.config.dcs_path
        if path is None:
            self.dcs_card.set_status(
                "Needs setup", "Choose your DCS Saved Games folder.", good=False
            )
            return
        ready, detail = inspect_installation(path)
        self.dcs_card.set_status(
            "Ready" if ready else "Needs setup", detail, good=ready
        )

    def set_running(self, running: bool) -> None:
        self.run.setEnabled(not running)
        self.stop.setEnabled(running)
        self.runtime_card.set_status(
            "Running" if running else "Stopped",
            "Monitoring DCS and connected to the voice service."
            if running
            else "Start MARA before your flight.",
            good=running,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1060, 700)
        self.setMinimumSize(900, 620)
        self.config = DesktopConfig.load()
        self.config.save()
        self.auth = StoredAuthSession(self.config.cloud_url, self.config.device_id)
        self.auth_url = self.config.cloud_url
        self.token: TokenPair | None = None
        self.pool = QThreadPool.globalInstance()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._activity_filter = ActivityOutputFilter()

        self.stack = QStackedWidget()
        self.login = LoginPage()
        self.dashboard = DashboardPage(self.config)
        self.process.readyReadStandardOutput.connect(self._runtime_output)
        self.process.started.connect(lambda: self.dashboard.set_running(True))
        self.process.finished.connect(self._runtime_finished)
        self.stack.addWidget(self.login)
        self.stack.addWidget(self.dashboard)
        self.setCentralWidget(self.stack)
        self.login.email.setText(self.config.email)
        self.login.submitted.connect(self._authenticate)
        self.dashboard.install_requested.connect(self._install_bios)
        self.dashboard.save_requested.connect(self._save_settings)
        self.dashboard.run_requested.connect(self._start_runtime)
        self.dashboard.stop_requested.connect(self._stop_runtime)
        self.dashboard.logout_requested.connect(self._logout)
        self.dashboard.learn_ptt_requested.connect(self._learn_ptt_button)
        self.dashboard.learn_mute_requested.connect(self._learn_mute_button)
        self._restore_session()

    def _worker(
        self,
        action: Callable[[], Any],
        success: Callable[[Any], None],
        failure: Callable[[str], None],
    ) -> None:
        worker = Worker(action)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(failure)
        self.pool.start(worker)

    def _restore_session(self) -> None:
        self._worker(self.auth.restore, self._signed_in, lambda _error: None)

    def _authenticate(self, email: str, password: str, register: bool) -> None:
        if not email or not password:
            self.login.finish("Enter your email and password.")
            return
        self._worker(
            lambda: self.auth.login(email, password, register=register),
            lambda pair: self._signed_in(pair, email),
            self.login.finish,
        )

    def _signed_in(self, result: object, email: str | None = None) -> None:
        if not isinstance(result, TokenPair):
            return
        self.token = result
        if email:
            self.config.email = email
            self.config.save()
        self.login.finish()
        self.dashboard.account.setText(self.config.email or "Signed in")
        self.dashboard.account_card.set_status(
            "Authenticated", self.config.email or "This device is connected.", good=True
        )
        self.dashboard.refresh_setup_status()
        self.dashboard.set_running(False)
        self.stack.setCurrentWidget(self.dashboard)

    def _install_bios(self) -> None:
        self.dashboard.update_config()
        path = self.config.dcs_path
        if path is None:
            QMessageBox.warning(
                self, APP_NAME, "Choose a DCS Saved Games folder first."
            )
            return
        self.dashboard.install.setEnabled(False)
        self.dashboard.dcs_card.set_status(
            "Installing…", "Downloading and verifying DCS-BIOS.", good=False
        )
        self._worker(
            lambda: install_dcs_bios(path),
            self._bios_installed,
            self._bios_failed,
        )

    def _bios_installed(self, _result: object) -> None:
        self.dashboard.install.setEnabled(True)
        self.config.save()
        self.dashboard.refresh_setup_status()
        QMessageBox.information(
            self, APP_NAME, "DCS-BIOS is installed and Export.lua is configured."
        )

    def _bios_failed(self, error: str) -> None:
        self.dashboard.install.setEnabled(True)
        self.dashboard.refresh_setup_status()
        QMessageBox.critical(self, APP_NAME, error)

    def _learn_ptt_button(self) -> None:
        self.dashboard.begin_ptt_learning()
        self._worker(
            lambda: detect_joystick_button(timeout=10.0),
            self._ptt_button_learned,
            self._ptt_button_learning_failed,
        )

    def _ptt_button_learned(self, result: object) -> None:
        if not isinstance(result, JoystickButtonSelection):
            self.dashboard.finish_ptt_learning(error="Unexpected PTT detection result.")
            return
        self.dashboard.finish_ptt_learning(result)

    def _ptt_button_learning_failed(self, error: str) -> None:
        self.dashboard.finish_ptt_learning(error=error)

    def _learn_mute_button(self) -> None:
        self.dashboard.begin_mute_learning()
        self._worker(
            lambda: detect_joystick_button(timeout=10.0),
            self._mute_button_learned,
            self._mute_button_learning_failed,
        )

    def _mute_button_learned(self, result: object) -> None:
        if not isinstance(result, JoystickButtonSelection):
            self.dashboard.finish_mute_learning(
                error="Unexpected mute-button detection result."
            )
            return
        self.dashboard.finish_mute_learning(result)

    def _mute_button_learning_failed(self, error: str) -> None:
        self.dashboard.finish_mute_learning(error=error)

    def _save_settings(self) -> None:
        try:
            unchanged_account = self._save_settings_silently()
        except (AuthError, OSError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Settings could not be saved: {exc}")
            return
        if not unchanged_account:
            QMessageBox.information(
                self,
                APP_NAME,
                "The service URL changed. Sign in to the new service to continue.",
            )
            return
        QMessageBox.information(self, APP_NAME, "Settings saved.")
        self.dashboard.refresh_setup_status()

    def _start_runtime(self) -> None:
        try:
            unchanged_account = self._save_settings_silently()
        except (AuthError, OSError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Settings could not be saved: {exc}")
            return
        if not unchanged_account:
            QMessageBox.information(
                self,
                APP_NAME,
                "The service URL changed. Sign in to the new service before starting.",
            )
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("DCS_COPILOT_CLOUD_URL", self.config.cloud_url)
        environment.insert("DCS_COPILOT_DEVICE_ID", self.config.device_id)
        environment.insert("COPILOT_PTT_KEY", self.config.ptt_key)
        environment.insert("COPILOT_MUTE_KEY", self.config.assistant_mute_key)
        environment.insert(
            "COPILOT_PTT_DEVICE",
            "" if self.config.ptt_device_id is None else str(self.config.ptt_device_id),
        )
        environment.insert(
            "COPILOT_PTT_BUTTON",
            "" if self.config.ptt_button is None else str(self.config.ptt_button),
        )
        environment.insert(
            "COPILOT_MUTE_DEVICE",
            ""
            if self.config.assistant_mute_device_id is None
            else str(self.config.assistant_mute_device_id),
        )
        environment.insert(
            "COPILOT_MUTE_BUTTON",
            ""
            if self.config.assistant_mute_button is None
            else str(self.config.assistant_mute_button),
        )
        environment.insert("COPILOT_SPEECH_MODE", self.config.speech_mode)
        if self.config.dcs_path is not None:
            environment.insert(
                "DCS_BIOS_PATH", str(self.config.dcs_path / "Scripts" / "DCS-BIOS")
            )
        self.process.setProcessEnvironment(environment)
        self._activity_filter.reset()
        self.dashboard.logs.clear()
        if getattr(sys, "frozen", False):
            self.process.start(sys.executable, ["--runtime"])
        else:
            self.process.start(
                sys.executable, ["-m", "dcs_copilot.desktop.app", "--runtime"]
            )

    def _stop_runtime(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(3000):
            self.process.kill()

    def _runtime_output(self) -> None:
        output = bytes(self.process.readAllStandardOutput().data()).decode(
            errors="replace"
        )
        for line in self._activity_filter.feed(output):
            self.dashboard.logs.appendPlainText(line)

    def _runtime_finished(self, *_args: object) -> None:
        self._runtime_output()
        for line in self._activity_filter.flush():
            self.dashboard.logs.appendPlainText(line)
        self.dashboard.set_running(False)

    def _save_settings_silently(self) -> bool:
        self.dashboard.update_config()
        service_changed = self.config.cloud_url != self.auth_url
        if service_changed:
            self.auth = StoredAuthSession(self.config.cloud_url, self.config.device_id)
            self.auth_url = self.config.cloud_url
            self.token = None
        self.config.save()
        if getattr(sys, "frozen", False):
            configure_launch_at_login(self.config.launch_at_login, Path(sys.executable))
        if service_changed:
            self.stack.setCurrentWidget(self.login)
            return False
        return True

    def _logout(self) -> None:
        self._stop_runtime()
        try:
            self.auth.logout()
        except AuthError as exc:
            QMessageBox.warning(self, APP_NAME, f"Logout warning: {exc}")
        self.token = None
        self.stack.setCurrentWidget(self.login)

    def closeEvent(self, event: Any) -> None:
        self._stop_runtime()
        super().closeEvent(event)


def _stylesheet() -> str:
    return f"""
        QWidget {{ background: {DARK}; color: #e7eef8; font-size: 14px; }}
        QMainWindow {{ background: {DARK}; }}
        QLabel {{ background: transparent; }}
        QLabel#brand {{ color: {ACCENT}; font-weight: 800; letter-spacing: 3px; }}
        QLabel#hero {{ font-size: 38px; font-weight: 750; line-height: 1.1; }}
        QLabel#heroSmall {{ font-size: 28px; font-weight: 700; }}
        QLabel#sectionTitle {{ font-size: 23px; font-weight: 700; }}
        QLabel#muted {{ color: {MUTED}; }}
        QLabel#error {{ color: #fb7185; }}
        QLabel#eyebrow {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
        QLabel#statusValue {{ font-size: 21px; font-weight: 700; }}
        QFrame#loginCard, QFrame#statusCard {{ background: {PANEL}; border: 1px solid #22324a; border-radius: 14px; }}
        QLineEdit, QComboBox, QPlainTextEdit {{ background: #0d1728; border: 1px solid #2b3b54; border-radius: 7px; padding: 10px; selection-background-color: {ACCENT}; }}
        QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
        QPushButton {{ background: #1b2a40; border: 1px solid #30435f; border-radius: 7px; padding: 10px 16px; font-weight: 650; }}
        QPushButton:hover {{ background: #243754; }}
        QPushButton:disabled {{ color: #607089; background: #121c2b; }}
        QPushButton#primary {{ color: #06120d; background: {ACCENT}; border-color: {ACCENT}; }}
        QPushButton#primary:hover {{ background: #6ee7b7; }}
        QPushButton#link {{ background: transparent; border: none; color: {MUTED}; }}
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{ color: {MUTED}; padding: 12px 18px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ color: #e7eef8; border-bottom-color: {ACCENT}; }}
    """


def _runtime() -> int:
    config = DesktopConfig.load()
    settings = config.runtime_settings("stored-account")
    configure_logging(settings.log_level)
    return run_client(settings, stdin_ptt=False)


def main() -> int:
    if "--runtime" in sys.argv:
        return _runtime()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DCS Copilot")
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(DARK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7eef8"))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet())
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
