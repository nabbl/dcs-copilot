"""Backend compatibility probing and bounded local process supervision."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dcs_copilot_protocol import MARA_API_VERSION

from .desktop.config_store import app_data_dir, backend_http_url


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    status: str
    detail: str
    progress_percent: int | None = None


@dataclass(frozen=True, slots=True)
class BackendInfo:
    url: str
    mara_version: str
    api_version: str
    deployment: str
    capabilities: dict[str, bool]
    openai_configured: bool
    latency_ms: float
    operational: bool = True
    blocking_reasons: tuple[str, ...] = ()
    services: dict[str, ServiceInfo] = field(default_factory=dict)


def probe_backend(url: str, *, timeout: float = 2.0) -> BackendInfo:
    base = backend_http_url(url)
    started = time.monotonic()
    try:
        with urlopen(
            Request(base + "/ready", headers={"Accept": "application/json"}),
            timeout=timeout,
        ) as response:
            readiness = json.loads(response.read())
        if not isinstance(readiness, dict):
            raise BackendError("Backend returned invalid readiness information")
        readiness_status = readiness.get("status")
        if readiness_status != "ready":
            error = readiness.get("error")
            if isinstance(error, str) and error:
                raise BackendError(f"Backend initialization failed: {error}")
            progress = readiness.get("model_progress")
            if isinstance(progress, dict):
                name = progress.get("name", "Kokoro model")
                percent = progress.get("percent", 0)
                raise BackendError(f"Provisioning {name}: {percent}%")
            reasons = readiness.get("blocking_reasons")
            if isinstance(reasons, list) and reasons and isinstance(reasons[0], str):
                raise BackendError(reasons[0])
            raise BackendError("Backend is still initializing")
        request = Request(
            base + "/api/system/info", headers={"Accept": "application/json"}
        )
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        raise BackendError(f"Cannot connect to backend at {base}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BackendError("Backend returned invalid system information")
    api_version = payload.get("api_version")
    if not isinstance(api_version, str):
        raise BackendError("Backend did not report an API version")
    if api_version != MARA_API_VERSION:
        raise BackendError(
            f"Incompatible backend API {api_version}; this MARA requires API {MARA_API_VERSION}"
        )
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    openai_configured = bool(payload.get("openai_configured", False))
    reasons = payload.get("blocking_reasons")
    blocking_reasons = (
        tuple(str(reason) for reason in reasons if isinstance(reason, str))
        if isinstance(reasons, list)
        else ()
    )
    services_payload = payload.get("services")
    services: dict[str, ServiceInfo] = {}
    if isinstance(services_payload, dict):
        for name, raw_service in services_payload.items():
            if not isinstance(raw_service, dict):
                continue
            raw_progress = raw_service.get("progress_percent")
            services[str(name)] = ServiceInfo(
                status=str(raw_service.get("status", "unknown")),
                detail=str(raw_service.get("detail", "")),
                progress_percent=(
                    int(raw_progress) if isinstance(raw_progress, int | float) else None
                ),
            )
    if "openai" not in services:
        services["openai"] = ServiceInfo(
            status="configured" if openai_configured else "missing",
            detail="An OpenAI API key is configured."
            if openai_configured
            else "Add an OpenAI API key in MARA settings.",
        )
    return BackendInfo(
        url=base,
        mara_version=str(payload.get("mara_version", "unknown")),
        api_version=api_version,
        deployment=str(payload.get("deployment", "unknown")),
        capabilities={
            str(name): bool(enabled) for name, enabled in capabilities.items()
        },
        openai_configured=openai_configured,
        latency_ms=(time.monotonic() - started) * 1000,
        operational=bool(payload.get("operational", openai_configured)),
        blocking_reasons=blocking_reasons,
        services=services,
    )


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[Sequence[str], dict[str, str], TextIO], Process]
StatusCallback = Callable[[str], None]


def backend_command() -> list[str]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        candidates = (
            executable.parent.parent / "MaraBackend" / "MaraBackend.exe",
            executable.parent / "MaraBackend.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate)]
        raise BackendError("The installed MaraBackend.exe could not be found")
    return [sys.executable, "-m", "dcs_copilot_cloud.main"]


class LocalBackendManager:
    """Own only processes launched here and restart crashes a bounded number of times."""

    def __init__(
        self,
        url: str,
        *,
        command: Sequence[str] | None = None,
        startup_timeout: float = 300.0,
        poll_interval: float = 0.2,
        restart_limit: int = 2,
        process_factory: ProcessFactory | None = None,
        probe: Callable[..., BackendInfo] = probe_backend,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.url = url
        self.command = list(command) if command is not None else None
        self.startup_timeout = startup_timeout
        self.poll_interval = poll_interval
        self.restart_limit = restart_limit
        self._factory = process_factory or self._spawn
        self._probe = probe
        self._on_status = on_status
        self._process: Process | None = None
        self._log: TextIO | None = None
        self.log_path: Path | None = None
        self._owned = False
        self._stopping = threading.Event()
        self._monitor: threading.Thread | None = None
        self.restart_count = 0
        self.info: BackendInfo | None = None

    @property
    def owned(self) -> bool:
        return self._owned

    @property
    def pid(self) -> int | None:
        value = getattr(self._process, "pid", None)
        return value if isinstance(value, int) else None

    def start(self) -> BackendInfo:
        try:
            self.info = self._probe(self.url, timeout=min(2.0, self.startup_timeout))
            self._status("connected to independently running backend")
            self._owned = False
            self._report_ready(self.info)
            return self.info
        except BackendError:
            pass
        self._stopping.clear()
        self._launch()
        self.info = self._wait_ready()
        self._owned = True
        self._report_ready(self.info)
        self._start_monitor()
        return self.info

    def restart(self) -> BackendInfo:
        self.stop()
        self.restart_count = 0
        return self.start()

    def stop(self) -> None:
        self._stopping.set()
        process = self._process
        if self._owned and process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._process = None
        self._owned = False
        self._close_log()
        monitor = self._monitor
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(timeout=1)
        self._monitor = None
        self._status("local backend stopped")

    def _launch(self) -> None:
        parsed = urlparse(self.url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise BackendError("Refusing to manage a non-loopback backend")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        paths = app_data_dir()
        logs = paths / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._close_log()
        self.log_path = logs / "backend-process.log"
        self._log = self.log_path.open("a", encoding="utf-8")
        command = list(self.command or backend_command())
        command.extend(["serve", "--host", "127.0.0.1", "--port", str(port)])
        environment = dict(os.environ)
        environment.update(
            {
                "MARA_DEPLOYMENT": "local",
                "MARA_DATA_DIR": str(paths),
                "DCS_COPILOT_DEV_TOKEN": "local-dev-token",
            }
        )
        self._process = self._factory(command, environment, self._log)
        self._owned = True
        self._status("local backend starting")

    @staticmethod
    def _spawn(
        command: Sequence[str], environment: dict[str, str], log: TextIO
    ) -> Process:
        creationflags = 0x08000000 if sys.platform == "win32" else 0
        return subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

    def _wait_ready(self) -> BackendInfo:
        deadline = time.monotonic() + self.startup_timeout
        last_error = "backend did not answer"
        while time.monotonic() < deadline:
            process = self._process
            if process is None:
                break
            exit_code = process.poll()
            if exit_code is not None:
                self._close_log()
                raise BackendError(
                    f"Local backend exited during startup with code {exit_code}. "
                    f"See {self.log_path or 'the backend log'}"
                )
            try:
                return self._probe(self.url, timeout=max(0.1, self.poll_interval))
            except BackendError as exc:
                detail = str(exc)
                if detail != last_error:
                    last_error = detail
                    self._status(detail)
                if detail.startswith("Backend initialization failed:"):
                    self.stop()
                    raise
            time.sleep(self.poll_interval)
        self.stop()
        raise BackendError(
            f"Local backend readiness timed out: {last_error}. "
            f"See {self.log_path or 'the backend log'}"
        )

    def _start_monitor(self) -> None:
        self._monitor = threading.Thread(
            target=self._monitor_process,
            name="mara-backend-supervisor",
            daemon=True,
        )
        self._monitor.start()

    def _monitor_process(self) -> None:
        while not self._stopping.wait(self.poll_interval):
            process = self._process
            if process is None or process.poll() is None:
                continue
            if self.restart_count >= self.restart_limit:
                self._status("local backend stopped after repeated crashes")
                self._owned = False
                self._close_log()
                return
            self.restart_count += 1
            self._status(
                f"local backend crashed; restart {self.restart_count}/{self.restart_limit}"
            )
            try:
                self._launch()
                self.info = self._wait_ready()
            except BackendError as exc:
                self._status(str(exc))
                continue
            self._report_ready(self.info)

    def _report_ready(self, info: BackendInfo) -> None:
        if info.operational:
            self._status("local backend operational")
            return
        blocker = next(iter(info.blocking_reasons), "setup is incomplete")
        self._status(f"local backend running; {blocker}")

    def _close_log(self) -> None:
        log = self._log
        self._log = None
        if log is not None:
            try:
                log.close()
            except OSError:
                pass

    def _status(self, value: str) -> None:
        if self._on_status is not None:
            self._on_status(value)
