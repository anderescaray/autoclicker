"""The run loop. Pure Python, no GUI and no OS calls: screen, input and time are injected.

Safety rule: when anything is unclear (target missing, several matches, list not
updating, user moving the mouse) the runner stops clicking and asks.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

from . import vision
from .model import CLICK_IMAGE, CLICK_POINT, KEY, TEXT, WAIT, WAIT_IMAGE, Flow, Rect, Step

log = logging.getLogger(__name__)

POLL_S = 0.15
GONE_MIN_SCORE = 0.5  # "still there" threshold after a click: lenient, a pressed/repainting button counts
GONE_MARGIN = 0.3
GONE_PAD_PX = 12
MOUSE_TOLERANCE_PX = 15
CORNER_PX = 3

# Problem kinds
ANCHOR_MISSING = "anchor_missing"
ROW_OFFSCREEN = "row_offscreen"
STEP_MISSING = "step_missing"
STEP_AMBIGUOUS = "step_ambiguous"
STEP_STILL_THERE = "step_still_there"
LIST_UNCHANGED = "list_unchanged"
USER_MOUSE = "user_mouse"

# Answers to a problem
RETRY, STOP = "retry", "stop"

# Result statuses
FINISHED, LIMIT, STOPPED = "finished", "limit", "stopped"


class ScreenProvider(Protocol):
    def grab(self) -> np.ndarray:
        """BGR image of the work monitor, in monitor pixels."""


class InputController(Protocol):
    def click(self, x: int, y: int, button: str, clicks: int) -> None: ...
    def press(self, keys: str) -> None: ...
    def type_text(self, text: str) -> None: ...
    def position(self) -> tuple[int, int]: ...
    def maximize_window_at(self, x: int, y: int) -> None: ...
    def window_at(self, x: int, y: int) -> int:
        """Handle of the top-level window under a point (0 if unknown)."""
    def window_open(self, handle: int) -> bool: ...


class Clock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass
class Problem:
    kind: str
    message: str
    step_index: int | None = None
    expected: np.ndarray | None = None  # what we were looking for
    screen: np.ndarray | None = None  # what we saw


@dataclass
class RunResult:
    status: str
    items: int
    message: str


class StopRun(Exception):
    pass


class _StepProblem(Exception):
    def __init__(self, problem: Problem):
        super().__init__(problem.message)
        self.problem = problem


def probe_step(flow: Flow, images: dict[str, np.ndarray], frame: np.ndarray, step: Step) -> tuple[str, Rect | None]:
    """Look for a step's target once, without clicking. Returns (vision status, where it would click)."""
    if step.type in (CLICK_IMAGE, WAIT_IMAGE):
        status, m = vision.locate(frame, images[step.image], step.confidence)
        if not m:
            return status, None
        return status, Rect(m.x, m.y, m.w, m.h)
    if step.type == CLICK_POINT:
        status, a = vision.locate(frame, images[flow.anchor_image], flow.anchor_confidence)
        if status != vision.FOUND:
            return status, None
        return status, Rect(a.x + step.point.x - 6, a.y + step.point.y - 6, 12, 12)
    return vision.FOUND, None


class Runner:
    def __init__(self, flow: Flow, images: dict[str, np.ndarray], screen: ScreenProvider, inp: InputController,
                 clock: Clock | None = None,
                 ask: Callable[[Problem], str] | None = None,
                 on_progress: Callable[[int, int | None, str], None] | None = None,
                 stop_event: threading.Event | None = None):
        self.flow = flow
        self.images = images
        self.screen = screen
        self.inp = inp
        self.clock = clock or Clock()
        self.ask = ask or (lambda problem: STOP)
        self.on_progress = on_progress or (lambda item, step, label: None)
        self.stop_event = stop_event or threading.Event()
        self.anchor_img = images[flow.anchor_image]
        sample = flow.first_row.empty_sample
        self.empty_sample = images.get(sample) if sample else None
        self._mouse = None  # where the mouse should be; anything else means the user moved it
        self._size = None

    # --- public ---

    def run(self, max_items: int | None = None) -> RunResult:
        limit = max_items if max_items is not None else self.flow.run.max_items
        items = 0
        try:
            self._mouse = self.inp.position()
            anchor, _ = self._find_anchor()  # pre-flight: no click before the list is found
            if self.flow.run.maximize_window:
                self.inp.maximize_window_at(anchor.x + anchor.w // 2, anchor.y + anchor.h // 2)
                self._sleep(1.0)
            while True:
                anchor, frame = self._find_anchor()
                row = self._first_row(anchor, frame)
                if not vision.is_row_filled(row, self.flow.first_row.filled_score, self.empty_sample):
                    return self._result(FINISHED, items, f"List is empty. {items} item(s) processed.")
                if items >= limit:
                    return self._result(LIMIT, items, f"Limit of {limit} item(s) reached.")
                log.info("Item %d: start", items + 1)
                for i, step in enumerate(self.flow.steps):
                    self._run_step(items + 1, i, step, anchor)
                self._wait_list_change(row)
                items += 1
        except StopRun as e:
            return self._result(STOPPED, items, str(e))

    # --- internals ---

    def _result(self, status: str, items: int, message: str) -> RunResult:
        log.info("Run ended: %s (%d items) %s", status, items, message)
        return RunResult(status, items, message)

    def _grab(self) -> np.ndarray:
        frame = self.screen.grab()
        self._size = frame.shape[1], frame.shape[0]
        return frame

    def _check(self) -> None:
        """Stop/pause checks, called between every action and while waiting."""
        if self.stop_event.is_set():
            raise StopRun("Stopped by user.")
        pos = self.inp.position()
        if self._size and self._in_corner(pos):
            raise StopRun("Stopped: mouse moved to a screen corner (failsafe).")
        if (self.flow.run.pause_on_user_mouse and self._mouse is not None
                and math.dist(pos, self._mouse) > MOUSE_TOLERANCE_PX):
            self._handle(Problem(USER_MOUSE, "You moved the mouse. The run is paused."))
            self._mouse = self.inp.position()

    def _in_corner(self, pos: tuple[int, int]) -> bool:
        w, h = self._size
        x, y = pos
        near = lambda v, edge: abs(v - edge) <= CORNER_PX  # noqa: E731
        return (near(x, 0) or near(x, w - 1)) and (near(y, 0) or near(y, h - 1))

    def _sleep(self, seconds: float) -> None:
        end = self.clock.now() + seconds
        while True:
            self._check()
            left = end - self.clock.now()
            if left <= 0:
                return
            self.clock.sleep(min(POLL_S, left))

    def _handle(self, problem: Problem) -> None:
        """Ask the user what to do. Returns on retry, raises StopRun otherwise."""
        log.warning("Problem: %s (%s)", problem.message, problem.kind)
        if self.stop_event.is_set() or self.ask(problem) != RETRY:
            raise StopRun(problem.message)

    def _find_anchor(self) -> tuple[vision.Match, np.ndarray]:
        while True:
            self._check()
            frame = self._grab()
            status, m = vision.locate(frame, self.anchor_img, self.flow.anchor_confidence)
            if status == vision.FOUND:
                return m, frame
            msg = ("Cannot find the list (anchor)." if status == vision.MISSING
                   else "The list anchor appears more than once on screen.")
            self._handle(Problem(ANCHOR_MISSING, msg, expected=self.anchor_img, screen=frame))

    def _first_row(self, anchor: vision.Match, frame: np.ndarray) -> np.ndarray:
        while True:
            row = vision.crop(frame, vision.row_rect(anchor, self.flow.first_row.offset))
            if row is not None:
                return row
            self._handle(Problem(ROW_OFFSCREEN, "The first row is outside the screen.", screen=frame))
            anchor, frame = self._find_anchor()

    def _run_step(self, item: int, index: int, step: Step, anchor: vision.Match) -> None:
        total = len(self.flow.steps)
        while True:
            self.on_progress(item, index, step.label or step.describe())
            log.info("Item %d step %d/%d: %s", item, index + 1, total, step.describe())
            try:
                self._do_step(index, step, anchor)
                return
            except _StepProblem as e:
                self._handle(e.problem)

    def _do_step(self, index: int, step: Step, anchor: vision.Match) -> None:
        if step.type in (CLICK_IMAGE, WAIT_IMAGE):
            m = self._wait_for_image(index, step)
            if step.type == CLICK_IMAGE:
                x, y = m.x + step.click_offset.x, m.y + step.click_offset.y
                window = self.inp.window_at(x, y) if step.wait_until_gone else 0
                self._click(x, y, step.button, step.clicks)
                if step.wait_until_gone:
                    main = self.inp.window_at(anchor.x + anchor.w // 2, anchor.y + anchor.h // 2)
                    if window and window != main:  # the button is in its own window: wait for that window
                        self._wait_window_closed(index, step, window)
                    else:  # same window as the list: wait until the button is gone from where it was
                        self._wait_until_gone(index, step, m)
        elif step.type == CLICK_POINT:
            self._click(anchor.x + step.point.x, anchor.y + step.point.y, step.button, step.clicks)
        elif step.type == KEY:
            self._check()
            self.inp.press(step.keys)
        elif step.type == TEXT:
            self._check()
            self.inp.type_text(step.text)
        elif step.type == WAIT:
            self._sleep(step.seconds)
        if step.type != WAIT:
            self._sleep(step.delay_after_s)

    def _click(self, x: int, y: int, button: str, clicks: int) -> None:
        self._check()
        self.inp.click(x, y, button, clicks)
        self._mouse = (x, y)

    def _wait_for_image(self, index: int, step: Step) -> vision.Match:
        template = self.images[step.image]
        name = f"step {index + 1} of {len(self.flow.steps)}" + (f" ({step.label})" if step.label else "")
        deadline = self.clock.now() + step.timeout_s
        while True:
            self._check()
            frame = self._grab()
            status, m = vision.locate(frame, template, step.confidence)
            if status == vision.FOUND:
                return m
            if status == vision.AMBIGUOUS:
                raise _StepProblem(Problem(STEP_AMBIGUOUS, f"Found {name} in more than one place.",
                                           index, template, frame))
            if self.clock.now() >= deadline:
                raise _StepProblem(Problem(STEP_MISSING, f"Cannot find {name}.", index, template, frame))
            self._sleep(POLL_S)

    def _step_name(self, index: int, step: Step) -> str:
        return f"Step {index + 1} of {len(self.flow.steps)}" + (f" ({step.label})" if step.label else "")

    def _wait_window_closed(self, index: int, step: Step, window: int) -> None:
        """After clicking, wait until the window that held the target has closed."""
        deadline = self.clock.now() + step.timeout_s
        while self.inp.window_open(window):
            self._check()
            if self.clock.now() >= deadline:
                raise _StepProblem(Problem(STEP_STILL_THERE, f"{self._step_name(index, step)}: its window is "
                                           "still open after the click.", index, self.images[step.image],
                                           self._grab()))
            self._sleep(POLL_S)

    def _wait_until_gone(self, index: int, step: Step, where: vision.Match) -> None:
        """After clicking, wait until the target is gone from where it was.

        Only that spot is checked, with a low threshold, so a pressed or repainting button still counts
        as there; and it must be missing twice in a row, so a flicker isn't taken for closing.
        """
        template = self.images[step.image]
        threshold = max(GONE_MIN_SCORE, step.confidence - GONE_MARGIN)
        pad = GONE_PAD_PX
        area = Rect(where.x - pad, where.y - pad, where.w + 2 * pad, where.h + 2 * pad)
        deadline = self.clock.now() + step.timeout_s
        misses = 0
        while True:
            self._check()
            frame = self._grab()
            h, w = frame.shape[:2]
            x0, y0 = max(area.x, 0), max(area.y, 0)
            spot = frame[y0:min(area.y + area.h, h), x0:min(area.x + area.w, w)]
            misses = 0 if vision.find_all(spot, template, threshold, 1) else misses + 1
            if misses >= 2:
                return
            if self.clock.now() >= deadline:
                raise _StepProblem(Problem(STEP_STILL_THERE, f"{self._step_name(index, step)} is still on "
                                           "screen after clicking it.", index, template, frame))
            self._sleep(POLL_S)

    def _wait_list_change(self, before: np.ndarray) -> None:
        """Never process the same item twice: the first row must change (or the list empty)."""
        while True:
            deadline = self.clock.now() + self.flow.run.wait_list_change_s
            frame = None
            while self.clock.now() < deadline:
                self._check()
                frame = self._grab()
                status, a = vision.locate(frame, self.anchor_img, self.flow.anchor_confidence)
                if status == vision.FOUND:
                    row = vision.crop(frame, vision.row_rect(a, self.flow.first_row.offset))
                    if row is not None and (
                            vision.rows_differ(row, before)
                            or not vision.is_row_filled(row, self.flow.first_row.filled_score, self.empty_sample)):
                        return
                self._sleep(POLL_S)
            self._handle(Problem(LIST_UNCHANGED, "The list has not updated after processing the item.",
                                 expected=before, screen=frame))
