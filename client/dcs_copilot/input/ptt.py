"""Global Windows keyboard and joystick/HOTAS push-to-talk inputs."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable, Iterable
from ctypes import Structure, byref, c_uint, c_ulong, c_ushort, c_wchar
from dataclasses import dataclass
from typing import Any

HOTKEY_MODIFIERS = ("CTRL", "ALT", "SHIFT", "WIN")

_NAMED_KEY_VIRTUAL_CODES = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "PAUSE": 0x13,
    "CAPS LOCK": 0x14,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGE UP": 0x21,
    "PAGE DOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PRINT SCREEN": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}
_MODIFIER_VIRTUAL_CODES = {
    "CTRL": frozenset((0x11, 0xA2, 0xA3)),
    "ALT": frozenset((0x12, 0xA4, 0xA5)),
    "SHIFT": frozenset((0x10, 0xA0, 0xA1)),
    "WIN": frozenset((0x5B, 0x5C)),
}


class PTTUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JoystickDevice:
    """A controller exposed by the Windows multimedia joystick API."""

    device_id: int
    name: str
    button_count: int


@dataclass(frozen=True, slots=True)
class JoystickButtonSelection:
    device: JoystickDevice
    button: int


class _JoyCaps(Structure):
    _fields_ = [
        ("wMid", c_ushort),
        ("wPid", c_ushort),
        ("szPname", c_wchar * 32),
        ("wXmin", c_uint),
        ("wXmax", c_uint),
        ("wYmin", c_uint),
        ("wYmax", c_uint),
        ("wZmin", c_uint),
        ("wZmax", c_uint),
        ("wNumButtons", c_uint),
        ("wPeriodMin", c_uint),
        ("wPeriodMax", c_uint),
        ("wRmin", c_uint),
        ("wRmax", c_uint),
        ("wUmin", c_uint),
        ("wUmax", c_uint),
        ("wVmin", c_uint),
        ("wVmax", c_uint),
        ("wCaps", c_uint),
        ("wMaxAxes", c_uint),
        ("wNumAxes", c_uint),
        ("wMaxButtons", c_uint),
        ("szRegKey", c_wchar * 32),
        ("szOEMVxD", c_wchar * 260),
    ]


class _JoyInfoEx(Structure):
    _fields_ = [
        ("dwSize", c_ulong),
        ("dwFlags", c_ulong),
        ("dwXpos", c_ulong),
        ("dwYpos", c_ulong),
        ("dwZpos", c_ulong),
        ("dwRpos", c_ulong),
        ("dwUpos", c_ulong),
        ("dwVpos", c_ulong),
        ("dwButtons", c_ulong),
        ("dwButtonNumber", c_ulong),
        ("dwPOV", c_ulong),
        ("dwReserved1", c_ulong),
        ("dwReserved2", c_ulong),
    ]


class WinMMJoystickBackend:
    """Small adapter around winmm, kept injectable for deterministic tests."""

    _JOY_RETURNBUTTONS = 0x80

    def __init__(self, winmm: Any | None = None) -> None:
        if winmm is None:
            if sys.platform != "win32":
                raise PTTUnavailableError("joystick/HOTAS PTT requires Windows")
            try:
                winmm = getattr(ctypes, "WinDLL")("winmm")  # noqa: B009 - Windows-only API
            except (AttributeError, OSError) as exc:
                raise PTTUnavailableError(
                    "Windows joystick API is unavailable"
                ) from exc
        self._winmm = winmm

    def devices(self) -> list[JoystickDevice]:
        devices: list[JoystickDevice] = []
        for device_id in range(int(self._winmm.joyGetNumDevs())):
            caps = _JoyCaps()
            if (
                self._winmm.joyGetDevCapsW(
                    device_id, byref(caps), c_uint(self._sizeof(caps))
                )
                != 0
            ):
                continue
            # joyGetDevCaps can include a configured but currently unplugged device.
            if self.buttons(device_id) is None:
                continue
            devices.append(
                JoystickDevice(
                    device_id,
                    _friendly_joystick_name(caps.szRegKey)
                    or caps.szPname
                    or f"Controller {device_id}",
                    int(caps.wNumButtons),
                )
            )
        return devices

    def buttons(self, device_id: int) -> int | None:
        state = _JoyInfoEx()
        state.dwSize = self._sizeof(state)
        state.dwFlags = self._JOY_RETURNBUTTONS
        result = self._winmm.joyGetPosEx(device_id, byref(state))
        return int(state.dwButtons) if result == 0 else None

    @staticmethod
    def _sizeof(value: Structure) -> int:
        from ctypes import sizeof

        return sizeof(value)


def discover_joysticks(
    *, platform: str = sys.platform, backend: Any | None = None
) -> list[JoystickDevice]:
    """Return connected Windows game controllers and their button capacity."""

    if platform != "win32":
        return []
    return list((backend or WinMMJoystickBackend()).devices())


def detect_joystick_button(
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.02,
    platform: str = sys.platform,
    backend: Any | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> JoystickButtonSelection:
    """Wait for the next newly pressed joystick button and identify it."""

    if platform != "win32":
        raise PTTUnavailableError("joystick/HOTAS PTT detection requires Windows")
    if timeout <= 0:
        raise ValueError("PTT detection timeout must be greater than zero")
    if poll_interval <= 0:
        raise ValueError("PTT detection poll interval must be greater than zero")
    joystick_backend = backend or WinMMJoystickBackend()
    devices = joystick_backend.devices()
    if not devices:
        raise PTTUnavailableError("no joystick/HOTAS controllers are connected")
    baseline = {
        device.device_id: joystick_backend.buttons(device.device_id) or 0
        for device in devices
    }
    deadline = clock() + timeout
    while clock() <= deadline:
        for device in devices:
            current = joystick_backend.buttons(device.device_id)
            if current is None:
                continue
            newly_pressed = current & ~baseline.get(device.device_id, 0)
            if newly_pressed:
                return JoystickButtonSelection(
                    device=device,
                    button=_first_pressed_button(newly_pressed),
                )
        sleep(poll_interval)
    raise PTTUnavailableError("no joystick/HOTAS button press was detected")


def _first_pressed_button(button_mask: int) -> int:
    return (button_mask & -button_mask).bit_length()


def _friendly_joystick_name(registry_key: str) -> str | None:
    if sys.platform != "win32" or not registry_key:
        return None
    try:
        import winreg

        subkey = (
            r"System\CurrentControlSet\Control\MediaProperties"
            rf"\PrivateProperties\Joystick\OEM\{registry_key}"
        )
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    value, _kind = winreg.QueryValueEx(key, "OEMName")
                if isinstance(value, str) and value.strip():
                    return value.strip()
            except FileNotFoundError:
                continue
    except OSError:
        return None
    return None


def function_key_virtual_code(key_name: str) -> int:
    normalized = key_name.strip().upper()
    if not normalized.startswith("F") or not normalized[1:].isdigit():
        raise ValueError("key must be a function key from F1 through F24")
    number = int(normalized[1:])
    if not 1 <= number <= 24:
        raise ValueError("key must be a function key from F1 through F24")
    return 0x70 + number - 1


def keyboard_key_names() -> tuple[str, ...]:
    """Return the keyboard keys offered by the desktop binding editor."""

    return (
        *(f"F{number}" for number in range(1, 25)),
        *(chr(code) for code in range(ord("A"), ord("Z") + 1)),
        *(str(number) for number in range(10)),
        *tuple(_NAMED_KEY_VIRTUAL_CODES),
    )


def keyboard_key_virtual_code(key_name: str) -> int:
    normalized = key_name.strip().upper()
    if normalized.startswith("F") and normalized[1:].isdigit():
        return function_key_virtual_code(normalized)
    if len(normalized) == 1 and ("A" <= normalized <= "Z" or "0" <= normalized <= "9"):
        return ord(normalized)
    try:
        return _NAMED_KEY_VIRTUAL_CODES[normalized]
    except KeyError as exc:
        raise ValueError("unsupported keyboard key") from exc


def split_hotkey(binding: str) -> tuple[frozenset[str], str]:
    """Parse a persisted hotkey into normalized modifiers and its base key."""

    parts = [part.strip().upper() for part in binding.split("+") if part.strip()]
    if not parts:
        raise ValueError("keyboard hotkey cannot be empty")
    key = parts[-1]
    modifiers = parts[:-1]
    if len(set(modifiers)) != len(modifiers) or any(
        modifier not in HOTKEY_MODIFIERS for modifier in modifiers
    ):
        raise ValueError("hotkey modifiers must be Ctrl, Alt, Shift, or Win")
    keyboard_key_virtual_code(key)
    return frozenset(modifiers), key


def format_hotkey(key_name: str, modifiers: Iterable[str] = ()) -> str:
    """Create the canonical string stored in settings and environment variables."""

    key = key_name.strip().upper()
    keyboard_key_virtual_code(key)
    selected = {str(modifier).strip().upper() for modifier in modifiers}
    unknown = selected.difference(HOTKEY_MODIFIERS)
    if unknown:
        raise ValueError("hotkey modifiers must be Ctrl, Alt, Shift, or Win")
    return "+".join((*filter(selected.__contains__, HOTKEY_MODIFIERS), key))


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
        self.modifiers, self.key_name = split_hotkey(key_name)
        self.hotkey = format_hotkey(self.key_name, self.modifiers)
        self.virtual_key = keyboard_key_virtual_code(self.key_name)
        self._on_pressed = on_press
        self._on_released = on_release
        self._platform = platform
        self._listener_factory = listener_factory
        self._listener: Any = None
        self._pressed = False
        self._pressed_modifier_keys: set[int] = set()

    def start(self) -> None:
        if self._platform != "win32":
            raise PTTUnavailableError(
                "global keyboard input requires Windows; use --stdin-ptt for local development"
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
        self._pressed_modifier_keys.clear()

    def _press(self, key: object) -> None:
        virtual_key = _virtual_key(key)
        modifier = _modifier_for_virtual_key(virtual_key)
        if modifier is not None and virtual_key is not None:
            self._pressed_modifier_keys.add(virtual_key)
            return
        if (
            virtual_key == self.virtual_key
            and _modifiers_for_virtual_keys(self._pressed_modifier_keys)
            == self.modifiers
            and not self._pressed
        ):
            self._pressed = True
            self._on_pressed()

    def _release(self, key: object) -> None:
        virtual_key = _virtual_key(key)
        modifier = _modifier_for_virtual_key(virtual_key)
        if modifier is not None and virtual_key is not None:
            self._pressed_modifier_keys.discard(virtual_key)
            return
        if virtual_key == self.virtual_key and self._pressed:
            self._pressed = False
            self._on_released()


class GlobalFunctionKeyHotkey(GlobalFunctionKeyPTT):
    """Emit one callback per global function-key press."""

    def __init__(
        self,
        key_name: str,
        *,
        on_press: Callable[[], None],
        platform: str = sys.platform,
        listener_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(
            key_name,
            on_press=on_press,
            on_release=lambda: None,
            platform=platform,
            listener_factory=listener_factory,
        )


class GlobalJoystickButtonPTT:
    """Poll a Windows joystick button and emit only press/release edges."""

    def __init__(
        self,
        device_id: int,
        button: int,
        *,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        platform: str = sys.platform,
        backend: Any | None = None,
        poll_interval: float = 0.01,
    ) -> None:
        if device_id < 0:
            raise ValueError("PTT controller device id cannot be negative")
        if not 1 <= button <= 32:
            raise ValueError("PTT controller button must be from 1 through 32")
        self.device_id = device_id
        self.button = button
        self._on_pressed = on_press
        self._on_released = on_release
        self._platform = platform
        self._backend = backend
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pressed = False

    def start(self) -> None:
        if self._platform != "win32":
            raise PTTUnavailableError("joystick/HOTAS PTT requires Windows")
        if self._thread is not None:
            return
        backend = self._backend or WinMMJoystickBackend()
        devices = {device.device_id: device for device in backend.devices()}
        device = devices.get(self.device_id)
        if device is None:
            raise PTTUnavailableError(
                f"PTT controller {self.device_id} is not connected"
            )
        if self.button > device.button_count:
            raise PTTUnavailableError(
                f"{device.name} has {device.button_count} buttons; "
                f"button {self.button} is unavailable"
            )
        self._backend = backend
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll, name="hotas-ptt", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        self._thread = None
        self._stop_event.set()
        if thread is not None:
            thread.join(timeout=1.0)
        if self._pressed:
            self._pressed = False
            self._on_released()

    def _poll(self) -> None:
        mask = 1 << (self.button - 1)
        backend = self._backend
        if backend is None:
            return
        while not self._stop_event.is_set():
            buttons = backend.buttons(self.device_id)
            pressed = buttons is not None and bool(buttons & mask)
            if pressed != self._pressed:
                self._pressed = pressed
                (self._on_pressed if pressed else self._on_released)()
            self._stop_event.wait(self._poll_interval)


class GlobalJoystickButtonHotkey(GlobalJoystickButtonPTT):
    """Emit one callback per joystick/HOTAS button press."""

    def __init__(
        self,
        device_id: int,
        button: int,
        *,
        on_press: Callable[[], None],
        platform: str = sys.platform,
        backend: Any | None = None,
        poll_interval: float = 0.01,
    ) -> None:
        super().__init__(
            device_id,
            button,
            on_press=on_press,
            on_release=lambda: None,
            platform=platform,
            backend=backend,
            poll_interval=poll_interval,
        )


def _virtual_key(key: object) -> int | None:
    direct = getattr(key, "vk", None)
    if isinstance(direct, int):
        return direct
    value = getattr(key, "value", None)
    nested = getattr(value, "vk", None)
    return nested if isinstance(nested, int) else None


def _modifier_for_virtual_key(virtual_key: int | None) -> str | None:
    return next(
        (
            modifier
            for modifier, virtual_keys in _MODIFIER_VIRTUAL_CODES.items()
            if virtual_key in virtual_keys
        ),
        None,
    )


def _modifiers_for_virtual_keys(virtual_keys: set[int]) -> frozenset[str]:
    return frozenset(
        modifier
        for modifier, modifier_keys in _MODIFIER_VIRTUAL_CODES.items()
        if not virtual_keys.isdisjoint(modifier_keys)
    )
