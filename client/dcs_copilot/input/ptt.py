"""Windows global function-key PTT without injecting keys into DCS."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any


class PTTUnavailableError(RuntimeError):
    pass


def function_key_virtual_code(key_name: str) -> int:
    normalized = key_name.strip().upper()
    if not normalized.startswith("F") or not normalized[1:].isdigit():
        raise ValueError("COPILOT_PTT_KEY must be a function key from F1 through F24")
    number = int(normalized[1:])
    if not 1 <= number <= 24:
        raise ValueError("COPILOT_PTT_KEY must be a function key from F1 through F24")
    return 0x70 + number - 1


class GlobalFunctionKeyPTT:
    def __init__(
        self,
        key_name: str,
        *,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        platform: str = sys.platform,
        listener_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.key_name = key_name.strip().upper()
        self.virtual_key = function_key_virtual_code(self.key_name)
        self._on_pressed = on_press
        self._on_released = on_release
        self._platform = platform
        self._listener_factory = listener_factory
        self._listener: Any = None
        self._pressed = False

    def start(self) -> None:
        if self._platform != "win32":
            raise PTTUnavailableError(
                "global F-key PTT requires Windows; use --stdin-ptt for local development"
            )
        factory = self._listener_factory
        if factory is None:
            try:
                from pynput import keyboard  # type: ignore[import-untyped]
            except ImportError as exc:
                raise PTTUnavailableError("pynput is not installed") from exc
            factory = keyboard.Listener
        self._listener = factory(on_press=self._press, on_release=self._release)
        self._listener.start()

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
            listener.join(timeout=1.0)
        if self._pressed:
            self._pressed = False
            self._on_released()

    def _press(self, key: object) -> None:
        if _virtual_key(key) == self.virtual_key and not self._pressed:
            self._pressed = True
            self._on_pressed()

    def _release(self, key: object) -> None:
        if _virtual_key(key) == self.virtual_key and self._pressed:
            self._pressed = False
            self._on_released()


def _virtual_key(key: object) -> int | None:
    direct = getattr(key, "vk", None)
    if isinstance(direct, int):
        return direct
    value = getattr(key, "value", None)
    nested = getattr(value, "vk", None)
    return nested if isinstance(nested, int) else None
