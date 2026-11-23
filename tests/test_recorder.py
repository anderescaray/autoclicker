from acv.model import CLICK_IMAGE, CLICK_POINT
from acv.recorder import Recorder, step_from_click
from test_engine import ACCEPT_BTN, ANCHOR, ROW0_Y, FakeApp, build_flow


def test_click_on_first_row_becomes_anchor_relative():
    flow, images = build_flow()
    rec = step_from_click(flow, images["anchor"], FakeApp(3).render(), 120, ROW0_Y + 10, "left")
    assert rec.step.type == CLICK_POINT
    assert (rec.step.point.x, rec.step.point.y) == (120 - ANCHOR.x, ROW0_Y + 10 - ANCHOR.y)
    assert rec.image is None


def test_click_on_button_becomes_unique_image():
    flow, images = build_flow()
    app = FakeApp(3)
    app.selected = app.dialog = True
    x, y = ACCEPT_BTN.x + 20, ACCEPT_BTN.y + 10
    rec = step_from_click(flow, images["anchor"], app.render(), x, y, "left")
    assert rec.step.type == CLICK_IMAGE
    assert rec.warning is None
    h, w = rec.image.shape[:2]
    assert 0 <= rec.step.click_offset.x < w and 0 <= rec.step.click_offset.y < h


def test_double_click_detection():
    flow, images = build_flow()
    rec = Recorder.__new__(Recorder)  # no listeners: only the event processing
    rec.flow, rec.anchor_img, rec._last_click = flow, images["anchor"], None
    frame = FakeApp(3).render()
    first = rec._process(("click", frame, 500, 430, "left", 1.0))
    second = rec._process(("click", frame, 501, 431, "left", 1.2))
    third = rec._process(("click", frame, 501, 431, "left", 3.0))
    assert first.step is not None and second.double_click and third.step is not None
