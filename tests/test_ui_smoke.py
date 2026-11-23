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


def test_main_window_lists_flows_and_opens_editor(app):
    from acv.ui.main_window import MainWindow
    flow = saved_flow()
    win = MainWindow()
    assert win.flows.count() == 1
    assert win.current_id() == flow.id
    assert win.editor.flow.id == flow.id
    assert win.editor.steps.count() == 2
    win.editor.shutdown()


def test_editor_reorders_saves_and_tracks_changes(app):
    from acv.ui.main_window import MainWindow
    flow = saved_flow()
    win = MainWindow()
    editor = win.editor
    assert not editor.is_dirty()
    editor.steps.setCurrentRow(0)
    editor.move_step(1)
    assert editor.is_dirty()
    assert editor.flow.steps[1].type == CLICK_IMAGE
    editor.save()
    assert not editor.is_dirty()
    assert storage.load_flow(flow.id).steps[1].type == CLICK_IMAGE
    editor.shutdown()


def test_empty_state_without_flows(app):
    from acv.ui.main_window import MainWindow
    win = MainWindow()
    assert win.stack.currentWidget() is win.empty
    win.editor.shutdown()


def test_dialogs_build(app):
    from acv.ui.dialogs import ProblemDialog, StepDialog
    img = np.zeros((40, 80, 3), np.uint8)
    for step in (Step(type=CLICK_IMAGE), Step(type=KEY, keys="f5")):
        StepDialog(step, img)
    for kind in (engine.ANCHOR_MISSING, engine.STEP_MISSING, engine.USER_MOUSE):
        ProblemDialog(engine.Problem(kind, "msg", 0, img, np.zeros((300, 400, 3), np.uint8))).grab()


def test_custom_widgets_paint(app):
    from acv.ui import widgets
    from acv.ui.recording_bar import RecordingBar
    from acv.ui.run_controller import RunPanel
    host = QtWidgets.QWidget()
    host.resize(600, 400)
    seg = widgets.SegmentedControl(["Monitor 1", "Monitor 2"])
    seg.set_index(1, emit=True)
    sw = widgets.Switch()
    sw.setChecked(True)
    dot = widgets.LiveDot()
    dot.set_state("ok")
    ring = widgets.ProgressRing()
    ring.set_progress(3, 5)
    snack = widgets.Snackbar(host)
    snack.show_message("Saved")
    steps = widgets.StepList()
    steps.addItem("Step")
    steps.set_state(0, "found")
    bar = RecordingBar()
    bar.set_count(3)
    bar.warn("Careful")
    panel = RunPanel(Flow(name="Demo"), 5)
    panel.set_progress(2, 1, 6, "Approve")
    for w in (widgets.PillButton("Run", "filled", play=True), widgets.PillButton("Record", dot=True),
              widgets.RoundButton("+", "New"), seg, sw, dot, ring, snack, steps, widgets.WarnIcon(), bar, panel):
        assert not w.grab().isNull()


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


def test_last_run_wording():
    import datetime

    from acv.ui.main_window import _when
    flow = Flow(steps=[Step()])
    day = datetime.date(2026, 11, 23)
    assert _when(flow, day) == "1 step · not run yet"
    flow.last_run = "2026-11-23 09:42 · 3 item(s) · finished"
    assert _when(flow, day) == "1 step · ran today, 09:42"
    assert _when(flow, day + datetime.timedelta(days=1)) == "1 step · ran yesterday"
    assert _when(flow, day + datetime.timedelta(days=5)) == "1 step · ran 23 Nov"
