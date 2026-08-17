from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from dcs_copilot.backend import (
    BackendError,
    BackendInfo,
    LocalBackendManager,
    probe_backend,
)

INFO = BackendInfo(
    "http://127.0.0.1:47100",
    "0.1.0",
    "1",
    "local",
    {"coach": True},
    False,
    1.0,
)


class FakeProcess:
    def __init__(self, exit_code: int | None = None) -> None:
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False
        self.pid = 123

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.exit_code is None:
            raise TimeoutError
        return self.exit_code


class JsonResponse:
    def __init__(self, document: dict[str, object]) -> None:
        self.payload = json.dumps(document).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.payload


def test_probe_rejects_incompatible_backend_api(monkeypatch) -> None:
    responses = iter(
        (
            JsonResponse({"status": "ready"}),
            JsonResponse(
                {
                    "mara_version": "9.0.0",
                    "api_version": "2",
                    "deployment": "remote",
                    "capabilities": {},
                }
            ),
        )
    )
    monkeypatch.setattr(
        "dcs_copilot.backend.urlopen", lambda *_a, **_k: next(responses)
    )
    with pytest.raises(BackendError, match="requires API 1"):
        probe_backend("https://mara.example")


def test_existing_backend_is_reused_and_not_stopped(
    tmp_path: Path, monkeypatch
) -> None:
    process = FakeProcess()
    launches = []
    manager = LocalBackendManager(
        "ws://127.0.0.1:47100/v2/realtime",
        command=["backend"],
        process_factory=lambda *args: launches.append(args) or process,
        probe=lambda *_args, **_kwargs: INFO,
    )

    assert manager.start() == INFO
    assert not manager.owned
    manager.stop()
    assert launches == []
    assert not process.terminated


def test_missing_backend_is_launched_and_owned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("dcs_copilot.backend.app_data_dir", lambda: tmp_path)
    process = FakeProcess()
    calls = 0

    def probe(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BackendError("offline")
        return INFO

    manager = LocalBackendManager(
        "ws://127.0.0.1:47100/v2/realtime",
        command=["backend"],
        process_factory=lambda *_args: process,
        probe=probe,
        poll_interval=0.001,
    )
    assert manager.start() == INFO
    assert manager.owned
    assert manager.pid == 123
    manager.stop()
    assert process.terminated


def test_crash_during_startup_is_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("dcs_copilot.backend.app_data_dir", lambda: tmp_path)
    manager = LocalBackendManager(
        "ws://127.0.0.1:47100/v2/realtime",
        command=["backend"],
        process_factory=lambda *_args: FakeProcess(17),
        probe=lambda *_args, **_kwargs: (_ for _ in ()).throw(BackendError("offline")),
        poll_interval=0.001,
    )
    with pytest.raises(BackendError, match="code 17"):
        manager.start()


def test_supervision_restarts_crash_but_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("dcs_copilot.backend.app_data_dir", lambda: tmp_path)
    processes = [FakeProcess(), FakeProcess(), FakeProcess()]
    launches = 0
    probes = 0
    statuses: list[str] = []

    def factory(*_args):
        nonlocal launches
        process = processes[launches]
        launches += 1
        return process

    def probe(*_args, **_kwargs):
        nonlocal probes
        probes += 1
        if probes == 1:
            raise BackendError("offline")
        return replace(INFO, latency_ms=float(probes))

    manager = LocalBackendManager(
        "ws://127.0.0.1:47100/v2/realtime",
        command=["backend"],
        process_factory=factory,
        probe=probe,
        poll_interval=0.002,
        restart_limit=2,
        on_status=statuses.append,
    )
    manager.start()
    processes[0].exit_code = 1
    deadline = time.monotonic() + 1
    while launches < 2 and time.monotonic() < deadline:
        time.sleep(0.005)
    processes[1].exit_code = 2
    while launches < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    processes[2].exit_code = 3
    while manager.owned and time.monotonic() < deadline:
        time.sleep(0.005)
    assert launches == 3
    assert manager.restart_count == 2
    assert any("repeated crashes" in status for status in statuses)
    manager.stop()
