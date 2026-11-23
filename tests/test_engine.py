"""Engine tests with a fake screen (a synthetic list app) and a fake mouse."""

import threading

import cv2
import numpy as np
import pytest

from acv import engine, vision
from acv.model import CLICK_IMAGE, CLICK_POINT, Flow, Point, Rect, Step

W, H = 640, 480
ANCHOR = Rect(40, 40, 160, 28)
ROW0_Y = 80  # first row top
ROW_H = 24
OPEN_BTN = Rect(480, 420, 90, 30)
ACCEPT_BTN = Rect(280, 260, 100, 30)


def button(img, r, text, color):
    cv2.rectangle(img, (r.x, r.y), (r.x + r.w, r.y + r.h), color, -1)
    cv2.putText(img, text, (r.x + 8, r.y + 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


class FakeApp:
    """A list of items; clicking first row -> Open -> Accept removes the first item."""

    def __init__(self, n, *, removes=True, dialog_works=True, show_anchor=True):
        self.items = [f"Item {i + 1}" for i in range(n)]
        self.selected = False
        self.dialog = False
        self.removes = removes
        self.dialog_works = dialog_works
        self.show_anchor = show_anchor

    def render(self):
        img = np.full((H, W, 3), 235, np.uint8)
        if self.show_anchor:
            button(img, ANCHOR, "PENDING", (120, 70, 30))
        for i, text in enumerate(self.items[:10]):
            y = ROW0_Y + i * ROW_H
            if i == 0 and self.selected:
                cv2.rectangle(img, (40, y), (400, y + ROW_H), (230, 200, 160), -1)
            cv2.putText(img, text, (48, y + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
        button(img, OPEN_BTN, "Open", (60, 140, 60))
        if self.dialog:
            cv2.rectangle(img, (200, 200), (460, 320), (250, 250, 250), -1)
            cv2.rectangle(img, (200, 200), (460, 320), (90, 90, 90), 1)
            button(img, ACCEPT_BTN, "Accept", (40, 40, 160))
        return img

    def click(self, x, y):
        inside = lambda r: r.x <= x < r.x + r.w and r.y <= y < r.y + r.h  # noqa: E731
        if self.dialog and inside(ACCEPT_BTN):
            self.dialog = False
            self.selected = False
            if self.removes:
                self.items.pop(0)
        elif inside(OPEN_BTN) and self.selected and self.dialog_works:
            self.dialog = True
        elif 40 <= x < 400 and ROW0_Y <= y < ROW0_Y + ROW_H and self.items:
            self.selected = True


class FakeScreen:
    def __init__(self, app):
        self.app = app

    def grab(self):
        return self.app.render()


class FakeInput:
    def __init__(self, app):
        self.app = app
        self.clicks = []
        self.pos = (320, 240)

    def click(self, x, y, button, clicks):
        self.clicks.append((x, y))
        self.pos = (x, y)
        self.app.click(x, y)

    def press(self, keys):
        pass

    def type_text(self, text):
        pass

    def position(self):
        return self.pos

    def maximize_window_at(self, x, y):
        pass


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def build_flow():
    """Record a flow from the fake app the way the editor would."""
    app = FakeApp(3)
    shot = app.render()
    images = {"anchor": vision.crop(shot, ANCHOR)}
    app.selected = True
    app.dialog = True
    shot = app.render()
    images["open"] = vision.crop(shot, OPEN_BTN)
    images["accept"] = vision.crop(shot, ACCEPT_BTN)
    flow = Flow(name="Test", anchor_image="anchor")
    offset = Rect(0, ROW0_Y - ANCHOR.y, 360, ROW_H)
    flow.first_row.offset = offset
    flow.first_row.filled_score = vision.row_score(vision.crop(FakeApp(1).render(), Rect(40, ROW0_Y, 360, ROW_H)))
    flow.steps = [
        Step(type=CLICK_POINT, point=Point(100, ROW0_Y - ANCHOR.y + 10), label="First row"),
        Step(type=CLICK_IMAGE, image="open", click_offset=Point(45, 15), label="Open"),
        Step(type=CLICK_IMAGE, image="accept", click_offset=Point(50, 15), label="Accept"),
    ]
    flow.run.wait_list_change_s = 2
    return flow, images


def make_runner(app, ask=None, stop=None):
    flow, images = build_flow()
    inp = FakeInput(app)
    problems = []

    def record(problem):
        problems.append(problem)
        return ask(problem) if ask else engine.STOP

    runner = engine.Runner(flow, images, FakeScreen(app), inp, FakeClock(), ask=record, stop_event=stop)
    return runner, inp, problems


def test_processes_all_items_then_finishes():
    app = FakeApp(5)
    runner, inp, problems = make_runner(app)
    result = runner.run()
    assert result.status == engine.FINISHED
    assert result.items == 5
    assert len(inp.clicks) == 5 * 3
    assert app.items == []
    assert problems == []


def test_empty_list_does_nothing():
    app = FakeApp(0)
    runner, inp, _ = make_runner(app)
    assert runner.run().status == engine.FINISHED
    assert inp.clicks == []


def test_no_anchor_means_no_clicks():
    app = FakeApp(3, show_anchor=False)
    runner, inp, problems = make_runner(app)
    result = runner.run()
    assert result.status == engine.STOPPED
    assert inp.clicks == []
    assert problems[0].kind == engine.ANCHOR_MISSING


def test_retry_after_anchor_appears():
    app = FakeApp(2, show_anchor=False)

    def ask(problem):
        app.show_anchor = True
        return engine.RETRY

    runner, inp, problems = make_runner(app, ask=ask)
    assert runner.run().status == engine.FINISHED
    assert len(problems) == 1


def test_missing_step_stops_at_that_step():
    app = FakeApp(3, dialog_works=False)
    runner, inp, problems = make_runner(app)
    result = runner.run()
    assert result.status == engine.STOPPED
    assert problems[0].kind == engine.STEP_MISSING
    assert problems[0].step_index == 2
    assert len(inp.clicks) == 2  # first row + Open, nothing after
    assert app.items[0] == "Item 1"


def test_list_not_updating_stops():
    app = FakeApp(3, removes=False)
    runner, inp, problems = make_runner(app)
    result = runner.run()
    assert result.status == engine.STOPPED
    assert problems[-1].kind == engine.LIST_UNCHANGED
    assert len(inp.clicks) == 3  # never processes the same item twice


def test_limit_is_respected():
    app = FakeApp(5)
    runner, inp, _ = make_runner(app)
    result = runner.run(max_items=2)
    assert result.status == engine.LIMIT
    assert result.items == 2
    assert len(app.items) == 3


def test_stop_event_stops_immediately():
    app = FakeApp(5)
    stop = threading.Event()
    stop.set()
    runner, inp, _ = make_runner(app, stop=stop)
    assert runner.run().status == engine.STOPPED
    assert inp.clicks == []


def test_user_moving_mouse_pauses_and_asks():
    app = FakeApp(2)
    runner, inp, problems = make_runner(app)
    original_click = inp.click

    def click_then_user_moves(*a):
        original_click(*a)
        inp.pos = (10, 300)  # the user grabs the mouse

    inp.click = click_then_user_moves
    result = runner.run()
    assert result.status == engine.STOPPED
    assert problems[0].kind == engine.USER_MOUSE
    assert len(inp.clicks) == 1


def test_mouse_in_corner_is_failsafe():
    app = FakeApp(2)
    runner, inp, _ = make_runner(app)
    runner.flow.run.pause_on_user_mouse = False
    original_click = inp.click

    def click_then_corner(*a):
        original_click(*a)
        inp.pos = (0, 0)

    inp.click = click_then_corner
    result = runner.run()
    assert result.status == engine.STOPPED
    assert "failsafe" in result.message
    assert len(inp.clicks) == 1


def test_ambiguous_step_stops():
    app = FakeApp(2)
    runner, inp, problems = make_runner(app)
    original_render = app.render

    def render_twice():
        img = original_render()
        if app.dialog:
            img[360:390, 40:140] = img[ACCEPT_BTN.y:ACCEPT_BTN.y + 30, ACCEPT_BTN.x:ACCEPT_BTN.x + 100]
        return img

    app.render = render_twice
    assert runner.run().status == engine.STOPPED
    assert problems[0].kind == engine.STEP_AMBIGUOUS


@pytest.mark.parametrize("step_index", [0, 1, 2])
def test_probe_step_finds_targets_without_clicking(step_index):
    flow, images = build_flow()
    app = FakeApp(2)
    app.selected = app.dialog = True
    status, r = engine.probe_step(flow, images, app.render(), flow.steps[step_index])
    assert status == vision.FOUND and r is not None
