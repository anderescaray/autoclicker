"""Real OS integration: DPI awareness, monitors, screen capture, mouse/keyboard, window handling.

Everything Windows-specific lives here so the rest of the app can be tested anywhere.
Coordinates given to/returned by the controllers are relative to the work monitor.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time

import mss
import numpy as np

from .model import MonitorInfo

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

# Keys a "Press key" step understands (pynput names), plus friendly aliases.
KEY_ALIASES = {"escape": "esc", "return": "enter", "control": "ctrl", "del": "delete",
               "pgup": "page_up", "pgdn": "page_down", "win": "cmd"}
SPECIAL_KEYS = {"enter", "tab", "esc", "space", "backspace", "delete", "insert", "home", "end",
                "page_up", "page_down", "up", "down", "left", "right", "ctrl", "shift", "alt", "cmd",
                *(f"f{i}" for i in range(1, 13))}


def parse_keys(combo: str) -> list[str]:
    """'Ctrl+Shift+S' -> ['ctrl', 'shift', 's']. Raises ValueError for unknown keys."""
    parts = [KEY_ALIASES.get(p.strip().lower(), p.strip().lower()) for p in combo.split("+")]
    if not parts or any(not p or (len(p) > 1 and p not in SPECIAL_KEYS) for p in parts):
        raise ValueError(f"Unknown key combination: {combo!r}")
    return parts


def set_dpi_awareness() -> None:
    """Per-monitor v2, so capture and click coordinates are the same physical pixels at 125 %/150 %."""
    if not IS_WINDOWS:
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def _monitor_scale(x: int, y: int) -> float:
    if not IS_WINDOWS:
        return 1.0
    try:
        from ctypes import wintypes
        hmon = ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return round(dpi_x.value / 96, 2)
    except (AttributeError, OSError):
        return 1.0


def list_monitors() -> list[MonitorInfo]:
    with mss.mss() as sct:
        return [MonitorInfo(index=i, left=m["left"], top=m["top"], width=m["width"], height=m["height"],
                            scale=_monitor_scale(m["left"] + m["width"] // 2, m["top"] + m["height"] // 2))
                for i, m in enumerate(sct.monitors[1:], start=1)]


def find_monitor(index: int) -> MonitorInfo | None:
    return next((m for m in list_monitors() if m.index == index), None)


class MssScreen:
    """Captures one monitor. mss handles are per-thread, so each thread gets its own."""

    def __init__(self, monitor: MonitorInfo):
        self.region = {"left": monitor.left, "top": monitor.top, "width": monitor.width, "height": monitor.height}
        self._local = threading.local()

    def grab(self) -> np.ndarray:
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = self._local.sct = mss.mss()
        return np.ascontiguousarray(np.asarray(sct.grab(self.region))[:, :, :3])


class PynputInput:
    """Mouse and keyboard through pynput, with window maximising through Win32."""

    def __init__(self, monitor: MonitorInfo):
        from pynput import keyboard, mouse
        self._mouse_mod, self._kb_mod = mouse, keyboard
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()
        self.left, self.top = monitor.left, monitor.top

    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        self.mouse.position = (self.left + x, self.top + y)
        time.sleep(0.05)  # let the target notice the hover before the click
        btn = self._mouse_mod.Button.right if button == "right" else self._mouse_mod.Button.left
        self.mouse.click(btn, clicks)

    def _key(self, name: str):
        return getattr(self._kb_mod.Key, name) if len(name) > 1 else self._kb_mod.KeyCode.from_char(name)

    def press(self, keys: str) -> None:
        keys = [self._key(k) for k in parse_keys(keys)]
        for k in keys:
            self.keyboard.press(k)
        for k in reversed(keys):
            self.keyboard.release(k)

    def type_text(self, text: str) -> None:
        self.keyboard.type(text)

    def position(self) -> tuple[int, int]:
        x, y = self.mouse.position
        return int(x) - self.left, int(y) - self.top

    def maximize_window_at(self, x: int, y: int) -> None:
        root = root_window_at(self.left + x, self.top + y)
        if root:
            ctypes.windll.user32.ShowWindow(root, 3)  # SW_MAXIMIZE


def root_window_at(x: int, y: int) -> int:
    """Top-level window handle under a global point (0 if unknown / not Windows)."""
    if not IS_WINDOWS:
        return 0
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return 0
    return user32.GetAncestor(hwnd, 2) or 0  # GA_ROOT


def key_name(key) -> str:
    """pynput key -> name used in steps ('f12', 'enter', 'a'...)."""
    name = getattr(key, "name", None)
    if name:
        return name
    char = getattr(key, "char", None)
    return char.lower() if char else ""


class HotkeyListener:
    """Global keyboard listener (works without focus). Calls on_key(name) from a background thread."""

    def __init__(self, on_key):
        from pynput import keyboard
        self._listener = keyboard.Listener(on_press=lambda k: on_key(key_name(k)))
        self._listener.daemon = True

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()
