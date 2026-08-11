from __future__ import annotations

from dataclasses import dataclass

import pytest
from dcs_copilot.input.ptt import (
    GlobalFunctionKeyHotkey,
    GlobalFunctionKeyPTT,
    GlobalJoystickButtonHotkey,
    GlobalJoystickButtonPTT,
    JoystickDevice,
    PTTUnavailableError,
    detect_joystick_button,
    discover_joysticks,
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


def test_global_function_hotkey_emits_once_per_press() -> None:
    events: list[str] = []
    listeners: list[FakeListener] = []

    def factory(**kwargs):
        listener = FakeListener(**kwargs)
        listeners.append(listener)
        return listener

    hotkey = GlobalFunctionKeyHotkey(
        "F14",
        on_press=lambda: events.append("toggle"),
        platform="win32",
        listener_factory=factory,
    )
    hotkey.start()
    key = FakeKey(function_key_virtual_code("F14"))
    listeners[0].on_press(key)
    listeners[0].on_press(key)
    listeners[0].on_release(key)
    listeners[0].on_press(key)
    assert events == ["toggle", "toggle"]
    hotkey.stop()


def test_ptt_validation_and_non_windows_failure() -> None:
    with pytest.raises(ValueError, match="F1 through F24"):
        function_key_virtual_code("F25")
    ptt = GlobalFunctionKeyPTT(
        "F13", on_press=lambda: None, on_release=lambda: None, platform="darwin"
    )
    with pytest.raises(PTTUnavailableError, match="Windows"):
        ptt.start()


class FakeJoystickBackend:
    def __init__(self) -> None:
        self.state = 0

    def devices(self) -> list[JoystickDevice]:
        return [JoystickDevice(2, "Throttle", 12)]

    def buttons(self, device_id: int) -> int | None:
        assert device_id == 2
        return self.state


class PressAfterBaselineBackend(FakeJoystickBackend):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def buttons(self, device_id: int) -> int | None:
        self.calls += 1
        assert device_id == 2
        return 0 if self.calls == 1 else 1 << 4


def test_joystick_button_ptt_is_edge_triggered() -> None:
    events: list[str] = []
    backend = FakeJoystickBackend()
    ptt = GlobalJoystickButtonPTT(
        2,
        5,
        on_press=lambda: events.append("down"),
        on_release=lambda: events.append("up"),
        platform="win32",
        backend=backend,
        poll_interval=0.001,
    )
    ptt.start()
    backend.state = 1 << 4
    assert _wait_until(lambda: events == ["down"])
    backend.state = 0
    assert _wait_until(lambda: events == ["down", "up"])
    ptt.stop()


def test_joystick_button_hotkey_emits_once_per_press() -> None:
    events: list[str] = []
    backend = FakeJoystickBackend()
    hotkey = GlobalJoystickButtonHotkey(
        2,
        5,
        on_press=lambda: events.append("toggle"),
        platform="win32",
        backend=backend,
        poll_interval=0.001,
    )
    hotkey.start()
    backend.state = 1 << 4
    assert _wait_until(lambda: events == ["toggle"])
    backend.state = 0
    assert _wait_until(lambda: not hotkey._pressed)
    backend.state = 1 << 4
    assert _wait_until(lambda: events == ["toggle", "toggle"])
    hotkey.stop()


def test_joystick_discovery_and_validation() -> None:
    backend = FakeJoystickBackend()
    assert discover_joysticks(platform="win32", backend=backend) == [
        JoystickDevice(2, "Throttle", 12)
    ]
    assert discover_joysticks(platform="darwin", backend=backend) == []
    with pytest.raises(ValueError, match="1 through 32"):
        GlobalJoystickButtonPTT(2, 33, on_press=lambda: None, on_release=lambda: None)


def test_detect_joystick_button_identifies_new_press() -> None:
    selection = detect_joystick_button(
        platform="win32",
        backend=PressAfterBaselineBackend(),
        timeout=1.0,
        poll_interval=0.001,
        sleep=lambda _seconds: None,
    )
    assert selection.device == JoystickDevice(2, "Throttle", 12)
    assert selection.button == 5


def test_detect_joystick_button_requires_windows_and_connected_device() -> None:
    with pytest.raises(PTTUnavailableError, match="requires Windows"):
        detect_joystick_button(platform="darwin")

    class EmptyBackend:
        def devices(self) -> list[JoystickDevice]:
            return []

    with pytest.raises(PTTUnavailableError, match="no joystick"):
        detect_joystick_button(platform="win32", backend=EmptyBackend())


def _wait_until(predicate, timeout: float = 0.2) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()
