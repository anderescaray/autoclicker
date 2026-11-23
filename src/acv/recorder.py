"""Turns the user's real clicks and special keys into flow steps.

The screen is captured the moment the button goes down (before the target app
reacts); the heavy work (finding a unique crop) runs on a worker thread.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import vision
from .desktop import HotkeyListener, MssScreen
from .model import CLICK_IMAGE, CLICK_POINT, KEY, Flow, MonitorInfo, Point, Step

log = logging.getLogger(__name__)
RECORDED_KEYS = {"enter", "tab", "esc", "f5", "up", "down", "left", "right", "space", "delete"}
DOUBLE_CLICK_S = 0.4


@dataclass
class Recorded:
    step: Step | None = None
    image: np.ndarray | None = None  # crop for click_image steps (saved by the UI)
    double_click: bool = False  # the previous click step becomes a double click
    warning: str | None = None


def step_from_click(flow: Flow, anchor_img: np.ndarray | None, frame: np.ndarray, x: int, y: int,
                    button: str) -> Recorded:
    """Build a step for a click at (x, y) on `frame` (monitor pixels).

    Clicks on the first row become anchor-relative clicks: the row's content
    changes for every item, so an image of it would never match again.
    """
    if anchor_img is not None and flow.first_row.offset.w:
        status, a = vision.locate(frame, anchor_img, flow.anchor_confidence)
        if status == vision.FOUND:
            r = vision.row_rect(a, flow.first_row.offset)
            if r.x <= x < r.x + r.w and r.y <= y < r.y + r.h:
                return Recorded(Step(type=CLICK_POINT, button=button, point=Point(x - a.x, y - a.y),
                                     label="First row"))
    crop, rect, unique = vision.crop_unique(frame, x, y, 0.85)
    warning = None if unique else ("The clicked spot looks the same as other places on screen. "
                                   "Check this step with 'Test step'.")
    step = Step(type=CLICK_IMAGE, button=button, image=None, click_offset=Point(x - rect.x, y - rect.y))
    return Recorded(step, crop, warning=warning)


class Recorder:
    """Listens globally to the mouse and keyboard. `on_recorded(Recorded)` is called from a worker thread."""

    def __init__(self, flow: Flow, anchor_img: np.ndarray | None, monitor: MonitorInfo, is_own_window, on_recorded,
                 record_keys: bool = True):
        self.flow, self.anchor_img, self.monitor = flow, anchor_img, monitor
        self.is_own_window = is_own_window  # callable(x, y) -> True for clicks on our own bar (ignored)
        self.on_recorded = on_recorded
        self.record_keys = record_keys
        self.screen = MssScreen(monitor)
        self._queue: queue.Queue = queue.Queue()
        self._last_click = None  # (time, x, y, button)
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._mouse = None
        self._keys = None

    def start(self) -> None:
        from pynput import mouse
        self._mouse = mouse.Listener(on_click=self._on_click)
        self._mouse.daemon = True
        self._mouse.start()
        if self.record_keys:
            self._keys = HotkeyListener(self._on_key)
            self._keys.start()
        self._worker.start()

    def stop(self) -> None:
        for listener in (self._mouse, self._keys):
            if listener:
                listener.stop()
        self._queue.put(None)

    # listener threads: keep these fast

    def _on_click(self, gx, gy, button, pressed):
        if not pressed:
            return
        name = getattr(button, "name", "left")
        if name not in ("left", "right"):
            return
        try:
            if self.is_own_window(int(gx), int(gy)):
                return
        except Exception:  # never let a listener thread die
            log.exception("Window check failed")
        m = self.monitor
        x, y = int(gx) - m.left, int(gy) - m.top
        if not (0 <= x < m.width and 0 <= y < m.height):
            self._queue.put(("warn", "Click outside the work monitor ignored."))
            return
        self._queue.put(("click", self.screen.grab(), x, y, name, time.monotonic()))

    def _on_key(self, name: str):
        if name in RECORDED_KEYS:
            self._queue.put(("key", name))

    # worker thread

    def _work(self):
        while (event := self._queue.get()) is not None:
            try:
                self.on_recorded(self._process(event))
            except Exception:
                log.exception("Could not record event")
                self.on_recorded(Recorded(warning="Could not record that action (see log)."))

    def _process(self, event) -> Recorded:
        kind = event[0]
        if kind == "warn":
            return Recorded(warning=event[1])
        if kind == "key":
            return Recorded(Step(type=KEY, keys=event[1], label=event[1].upper()))
        _, frame, x, y, button, t = event
        last, self._last_click = self._last_click, (t, x, y, button)
        if last and button == last[3] and t - last[0] < DOUBLE_CLICK_S and math.dist((x, y), last[1:3]) < 6:
            self._last_click = None
            return Recorded(double_click=True)
        return step_from_click(self.flow, self.anchor_img, frame, x, y, button)
