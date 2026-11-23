"""Build every window offscreen: catches import errors and broken layouts without a real desktop."""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from acv import engine, storage  # noqa: E402
from acv.model import CLICK_IMAGE, KEY, Flow, MonitorInfo, Rect, Step  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def saved_flow():
    flow = Flow(name="Approve requests", monitor=MonitorInfo(1, 0, 0, 800, 600, 1.0))
    img = np.random.default_rng(0).integers(0, 255, (24, 60, 3), dtype=np.uint8)
    flow.anchor_image = storage.add_flow_image(flow, img, "anchor")
    flow.first_row.offset = Rect(0, 30, 200, 20)
    flow.steps = [Step(type=CLICK_IMAGE, image=storage.add_flow_image(flow, img, "step"), label="OK"),
                  Step(type=KEY, keys="enter")]
    storage.save_flow(flow)
    return flow


def test_main_window_lists_flows(app):
    from acv.ui.main_window import MainWindow
    flow = saved_flow()
    win = MainWindow()
    assert win.table.topLevelItemCount() == 1
    assert win.current().id == flow.id
    win.close()


def test_flow_editor_builds_and_detects_changes(app, monkeypatch):
    from acv.ui.flow_editor import FlowEditor
    from acv.ui.run_controller import RunController
    flow = saved_flow()
    editor = FlowEditor(flow, RunController())
    assert editor.steps.count() == 2
    editor.move_step(1)  # nothing selected: no-op
    editor.steps.setCurrentRow(0)
    editor.move_step(1)
    assert flow.steps[1].type == CLICK_IMAGE
    editor.save()
    assert storage.load_flow(flow.id).steps[1].type == CLICK_IMAGE
    editor.close()


def test_dialogs_build(app):
    from acv.ui.dialogs import ProblemDialog, RunDialog, StepDialog
    img = np.zeros((40, 80, 3), np.uint8)
    for step in (Step(type=CLICK_IMAGE), Step(type=KEY, keys="f5")):
        StepDialog(step, img)
    RunDialog(Flow())
    for kind in (engine.ANCHOR_MISSING, engine.STEP_MISSING, engine.USER_MOUSE):
        ProblemDialog(engine.Problem(kind, "msg", 0, img, np.zeros((300, 400, 3), np.uint8)))


def test_tutorial_builds(app):
    from acv.ui.tutorial import Tutorial
    assert len(Tutorial().pageIds()) == 6


def test_region_picker_maps_to_frame_pixels(app):
    from PySide6.QtCore import QRect

    from acv.ui.region_picker import RegionPicker
    frame = np.zeros((1200, 1600, 3), np.uint8)  # e.g. a 125 % monitor: more pixels than widget units
    picker = RegionPicker(frame, MonitorInfo(1, 0, 0, 1600, 1200, 1.25), ["a"])
    picker.resize(800, 600)
    assert picker._to_frame(QRect(10, 20, 100, 50)) == Rect(20, 40, 200, 100)
