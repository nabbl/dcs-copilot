from __future__ import annotations

from dataclasses import dataclass

import pytest
from dcs_copilot.input.ptt import (
    GlobalFunctionKeyPTT,
    PTTUnavailableError,
    function_key_virtual_code,
)


@dataclass
class FakeKey:
    vk: int


class FakeListener:
    def __init__(self, *, on_press, on_release) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float) -> None:
        assert timeout == 1.0


def test_global_f13_ptt_is_edge_triggered() -> None:
    events: list[str] = []
    listeners: list[FakeListener] = []

    def factory(**kwargs):
        listener = FakeListener(**kwargs)
        listeners.append(listener)
        return listener

    ptt = GlobalFunctionKeyPTT(
        "F13",
        on_press=lambda: events.append("down"),
        on_release=lambda: events.append("up"),
        platform="win32",
        listener_factory=factory,
    )
    ptt.start()
    listeners[0].on_press(FakeKey(function_key_virtual_code("F13")))
    listeners[0].on_press(FakeKey(function_key_virtual_code("F13")))
    listeners[0].on_release(FakeKey(function_key_virtual_code("F13")))
    assert events == ["down", "up"]
    ptt.stop()
    assert listeners[0].stopped


def test_ptt_validation_and_non_windows_failure() -> None:
    with pytest.raises(ValueError, match="F1 through F24"):
        function_key_virtual_code("F25")
    ptt = GlobalFunctionKeyPTT(
        "F13", on_press=lambda: None, on_release=lambda: None, platform="darwin"
    )
    with pytest.raises(PTTUnavailableError, match="Windows"):
        ptt.start()
