"""Flow editor: monitor, anchor + first row with a live check, steps (record, edit, test) and run options."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .. import storage, vision
from ..desktop import IS_WINDOWS, MssScreen, list_monitors, root_window_at
from ..engine import probe_step
from ..model import (
    CLICK_IMAGE, CLICK_POINT, IMAGE_STEPS, KEY, STEP_TYPE_NAMES, STEP_TYPES, TEXT, WAIT, WAIT_IMAGE, Flow, Point,
    Step,
)
from ..recorder import Recorder
from .common import HighlightOverlay, hidden_windows, image_label, set_label_image, to_pixmap, wait_ms
from .dialogs import MonitorDialog, StepDialog
from .recording_bar import RecordingBar
from .region_picker import mark_list, pick_regions

log = logging.getLogger(__name__)


class LiveChecker(QThread):
    """Checks about twice a second whether the anchor is visible and the first row has content."""

    status = Signal(object, object)  # anchor found (bool | None), row filled (bool | None)

    def __init__(self, editor: FlowEditor):
        super().__init__()
        self.editor = editor
        self.last_row = None

    def run(self):
        screen, key = None, None
        while not self.isInterruptionRequested():
            try:
                cfg = self.editor.live_config()
                if cfg is None:
                    self.status.emit(None, None)
                else:
                    mon, anchor, offset, filled_score, empty = cfg
                    if key != (mon.left, mon.top, mon.width, mon.height):
                        screen, key = MssScreen(mon), (mon.left, mon.top, mon.width, mon.height)
                    frame = screen.grab()
                    found, a = vision.locate(frame, anchor, self.editor.flow.anchor_confidence)
                    filled = None
                    if found == vision.FOUND:
                        row = vision.crop(frame, vision.row_rect(a, offset))
                        if row is not None:
                            self.last_row = row
                            filled = vision.is_row_filled(row, filled_score, empty)
                    self.status.emit(found == vision.FOUND, filled)
            except Exception:
                log.exception("Live check failed")
            self.msleep(500)


class FlowEditor(QWidget):
    saved = Signal()
    closed = Signal()

    def __init__(self, flow: Flow, run_controller, is_new: bool = False, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.flow = flow
        self.run_controller = run_controller
        self.is_new = is_new
        self.images: dict = {}
        self._saved_state = None if is_new else flow.to_dict()
        self.recorder = None
        self.setWindowTitle(f"Edit flow — {flow.name}")
        self.resize(1100, 700)
        self._build()
        self._refresh_all()
        self.checker = LiveChecker(self)
        self.checker.status.connect(self._on_live_status)
        self.checker.start()

    # ---------- layout ----------

    def _build(self):
        root = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Flow name"))
        self.name = QLineEdit(self.flow.name)
        self.name.textChanged.connect(lambda t: setattr(self.flow, "name", t.strip()))
        name_row.addWidget(self.name, 1)
        root.addLayout(name_row)

        body = QHBoxLayout()
        left = QVBoxLayout()
        body.addLayout(left, 2)
        right = QVBoxLayout()
        body.addLayout(right, 3)
        root.addLayout(body, 1)

        # 1. monitor
        box = QGroupBox("1 · Work monitor")
        lay = QHBoxLayout(box)
        self.monitor_label = QLabel()
        lay.addWidget(self.monitor_label, 1)
        btn = QPushButton("Choose…")
        btn.clicked.connect(self.choose_monitor)
        lay.addWidget(btn)
        left.addWidget(box)

        # 2. list
        box = QGroupBox("2 · The list")
        lay = QVBoxLayout(box)
        thumbs = QFormLayout()
        self.anchor_thumb = image_label(None, 320, 60, "Not marked yet")
        self.row_thumb = image_label(None, 320, 40, "Not marked yet")
        thumbs.addRow("Anchor", self.anchor_thumb)
        thumbs.addRow("First row", self.row_thumb)
        lay.addLayout(thumbs)
        self.mark_btn = QPushButton("Mark anchor and first row")
        self.mark_btn.setObjectName("primary")
        self.mark_btn.clicked.connect(self.mark_list)
        lay.addWidget(self.mark_btn)
        live = QHBoxLayout()
        self.anchor_status = QLabel()
        self.row_status = QLabel()
        live.addWidget(self.anchor_status)
        live.addWidget(self.row_status)
        live.addStretch()
        lay.addLayout(live)
        self.empty_btn = QPushButton("Save current state as empty")
        self.empty_btn.setToolTip("Only needed if an empty row still shows lines or borders. "
                                  "Use it while the list is empty.")
        self.empty_btn.clicked.connect(self.save_empty_sample)
        lay.addWidget(self.empty_btn)
        left.addWidget(box)

        # run options
        box = QGroupBox("Run options")
        form = QFormLayout(box)
        self.max_items = QSpinBox()
        self.max_items.setRange(1, 100000)
        self.max_items.setValue(self.flow.run.max_items)
        self.max_items.valueChanged.connect(lambda v: setattr(self.flow.run, "max_items", v))
        self.wait_change = QDoubleSpinBox()
        self.wait_change.setRange(1, 600)
        self.wait_change.setSuffix(" s")
        self.wait_change.setValue(self.flow.run.wait_list_change_s)
        self.wait_change.valueChanged.connect(lambda v: setattr(self.flow.run, "wait_list_change_s", v))
        self.maximize = QCheckBox("Maximise the target window first")
        self.maximize.setChecked(self.flow.run.maximize_window)
        self.maximize.toggled.connect(lambda v: setattr(self.flow.run, "maximize_window", v))
        self.pause_mouse = QCheckBox("Pause if I move the mouse")
        self.pause_mouse.setChecked(self.flow.run.pause_on_user_mouse)
        self.pause_mouse.toggled.connect(lambda v: setattr(self.flow.run, "pause_on_user_mouse", v))
        form.addRow("Max items per run", self.max_items)
        form.addRow("Wait for the list to update", self.wait_change)
        form.addRow(self.maximize)
        form.addRow(self.pause_mouse)
        left.addWidget(box)
        left.addStretch()

        # 3. steps
        box = QGroupBox("3 · Steps (done once per item)")
        lay = QVBoxLayout(box)
        tools = QHBoxLayout()
        self.record_btn = QPushButton("● Record")
        self.record_btn.setObjectName("primary")
        self.record_btn.clicked.connect(self.start_recording)
        add = QPushButton("Add step")
        menu = QMenu(add)
        for t in STEP_TYPES:
            menu.addAction(STEP_TYPE_NAMES[t], lambda t=t: self.add_step(t))
        add.setMenu(menu)
        tools.addWidget(self.record_btn)
        tools.addWidget(add)
        tools.addStretch()
        for text, slot in (("Edit", self.edit_step), ("↑", lambda: self.move_step(-1)),
                           ("↓", lambda: self.move_step(1)), ("Delete", self.delete_step)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            tools.addWidget(b)
        lay.addLayout(tools)
        self.steps = QListWidget()
        self.steps.setIconSize(QSize(120, 48))
        self.steps.itemDoubleClicked.connect(lambda _: self.edit_step())
        lay.addWidget(self.steps, 1)
        tests = QHBoxLayout()
        for text, slot, tip in (
                ("Test step", self.test_step, "Find the selected step on screen and highlight it. No click."),
                ("Simulate", self.simulate, "Highlight every step in turn. No click."),
                ("Run 1 item", self.run_one, "Process only the first item of the list, for real.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            tests.addWidget(b)
        lay.addLayout(tests)
        right.addWidget(box)

        bottom = QHBoxLayout()
        self.message = QLabel()
        bottom.addWidget(self.message, 1)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(save)
        bottom.addWidget(close)
        root.addLayout(bottom)

    # ---------- helpers ----------

    def image(self, name: str | None):
        if not name:
            return None
        if name not in self.images:
            try:
                self.images[name] = storage.load_flow_image(self.flow, name)
            except (OSError, ValueError):
                log.exception("Missing image %s", name)
                return None
        return self.images[name]

    def all_images(self) -> dict:
        names = [self.flow.anchor_image, self.flow.first_row.empty_sample]
        names += [s.image for s in self.flow.steps if s.type in IMAGE_STEPS]
        return {n: self.image(n) for n in names if n}

    def add_image(self, img, prefix: str) -> str:
        name = storage.add_flow_image(self.flow, img, prefix)
        self.images[name] = img
        return name

    def live_config(self):
        """Read by the live checker thread."""
        f = self.flow
        anchor = self.images.get(f.anchor_image)
        if not f.monitor.width or anchor is None or not f.first_row.offset.w:
            return None
        return f.monitor, anchor, f.first_row.offset, f.first_row.filled_score, self.images.get(f.first_row.empty_sample)

    def say(self, text: str):
        self.message.setText(text)
        QTimer.singleShot(6000, self.message, lambda: self.message.text() == text and self.message.clear())

    def selected(self) -> int:
        return self.steps.currentRow()

    def need(self, monitor=True, anchor=False, steps=False) -> bool:
        f = self.flow
        missing = None
        if monitor and not f.monitor.width:
            missing = "Choose the work monitor first."
        elif anchor and not f.anchor_image:
            missing = "Mark the anchor and the first row first."
        elif steps and not f.steps:
            missing = "Record or add some steps first."
        if missing:
            QMessageBox.information(self, "Not yet", missing)
        return missing is None

    def capture(self):
        with hidden_windows():
            return MssScreen(self.flow.monitor).grab()

    # ---------- refresh ----------

    def _refresh_all(self):
        m = self.flow.monitor
        self.monitor_label.setText(f"Monitor {m.index}  ·  {m.width}×{m.height}  ·  {round(m.scale * 100)} %"
                                   if m.width else "Not chosen")
        set_label_image(self.anchor_thumb, self.image(self.flow.anchor_image), 320, 60, "Not marked yet")
        self._refresh_steps()

    def _refresh_steps(self, select: int | None = None):
        self.steps.clear()
        for i, s in enumerate(self.flow.steps, start=1):
            item = QListWidgetItem(f"{i}.  {s.describe()}")
            img = self.image(s.image) if s.type in IMAGE_STEPS else None
            if img is not None:
                item.setIcon(QIcon(to_pixmap(img, 120, 48)))
            self.steps.addItem(item)
        if select is not None and 0 <= select < self.steps.count():
            self.steps.setCurrentRow(select)

    def _on_live_status(self, anchor, filled):
        if anchor is None:
            self.anchor_status.setText("Anchor: —")
            self.row_status.setText("First row: —")
            return
        self.anchor_status.setText("Anchor: ✅ found" if anchor else "Anchor: ❌ not found")
        self.row_status.setText("" if not anchor else
                                "First row: ✅ has an item" if filled else "First row: ⬜ empty")
        if self.checker.last_row is not None and anchor:
            set_label_image(self.row_thumb, self.checker.last_row, 320, 40)

    # ---------- monitor & list ----------

    def choose_monitor(self):
        monitors = list_monitors()
        if len(monitors) == 1:
            chosen = monitors[0]
        else:
            dlg = MonitorDialog(monitors, self.flow.monitor.index if self.flow.monitor.width else None, self)
            if not dlg.exec() or not dlg.choice:
                return
            chosen = dlg.choice
        self.flow.monitor = chosen
        self._refresh_all()

    def mark_list(self):
        if not self.need():
            return
        frame = self.capture()
        marked = mark_list(frame, self.flow.monitor, self)
        self.activateWindow()
        if not marked:
            return
        anchor, offset, row = marked
        f = self.flow
        f.anchor_image = self.add_image(anchor, "anchor")
        f.first_row.offset = offset
        f.first_row.filled_score = vision.row_score(row)
        f.first_row.empty_sample = None
        f.monitor = next((m for m in list_monitors() if m.index == f.monitor.index), f.monitor)
        set_label_image(self.row_thumb, row, 320, 40)
        self._refresh_all()
        self.say("List marked. Check the live indicator below.")

    def save_empty_sample(self):
        row = self.checker.last_row
        if row is None:
            QMessageBox.information(self, "Not visible", "The list must be visible to save its empty state.")
            return
        if QMessageBox.question(self, "Save empty state",
                                "Is the list empty right now? The current first row will be treated as "
                                "'no more items'.") == QMessageBox.Yes:
            self.flow.first_row.empty_sample = self.add_image(row, "empty")
            self.say("Empty state saved.")

    # ---------- steps ----------

    def start_recording(self):
        if not self.need(anchor=True):
            return
        self.bar = RecordingBar()
        self.bar.undo.connect(self.undo_recorded)
        self.bar.finish.connect(self.stop_recording)
        self._hidden = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for w in self._hidden:
            w.hide()
        self.bar.place(self.flow.monitor)
        self.bar.show()
        self.bar.set_count(len(self.flow.steps))
        bar_handle = int(self.bar.winId())

        def is_bar(x, y):
            return self.bar.contains_physical(x, y) or (IS_WINDOWS and root_window_at(x, y) == bar_handle)

        self.recorder = Recorder(self.flow, self.image(self.flow.anchor_image), self.flow.monitor,
                                 is_bar, self.bar.recorded.emit)
        self.bar.recorded.connect(self._on_recorded)
        self.recorder.start()

    def _on_recorded(self, rec):
        if rec.step is not None:
            if rec.image is not None:
                rec.step.image = self.add_image(rec.image, "step")
            self.flow.steps.append(rec.step)
        elif rec.double_click and self.flow.steps and self.flow.steps[-1].type in (CLICK_IMAGE, CLICK_POINT):
            self.flow.steps[-1].clicks = 2
        if rec.warning:
            self.bar.warn(rec.warning)
        self.bar.set_count(len(self.flow.steps))

    def undo_recorded(self):
        if self.flow.steps:
            self.flow.steps.pop()
        self.bar.set_count(len(self.flow.steps))

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder = None
        self.bar.close()
        for w in self._hidden:
            w.show()
        self.activateWindow()
        self._refresh_steps(len(self.flow.steps) - 1)
        self.say("Recording finished. Review the steps, then try 'Simulate' or 'Run 1 item'.")

    def add_step(self, kind: str):
        step = Step(type=kind)
        if kind in (CLICK_IMAGE, WAIT_IMAGE, CLICK_POINT):
            if not self.need(anchor=kind == CLICK_POINT):
                return
            frame = self.capture()
            prompt = ("Drag around the spot to click (it will click the centre)." if kind != WAIT_IMAGE
                      else "Drag around what must appear before continuing.")
            rects = pick_regions(frame, self.flow.monitor, [prompt])
            self.activateWindow()
            if not rects:
                return
            r = rects[0]
            cx, cy = r.x + r.w // 2, r.y + r.h // 2
            if kind == CLICK_POINT:
                status, a = vision.locate(frame, self.image(self.flow.anchor_image), self.flow.anchor_confidence)
                if status != vision.FOUND:
                    QMessageBox.warning(self, "Anchor not visible", "The anchor must be visible to place this click.")
                    return
                step.point = Point(cx - a.x, cy - a.y)
            else:
                crop = vision.crop(frame, r)
                if vision.locate(frame, crop, step.confidence)[0] != vision.FOUND:
                    QMessageBox.warning(self, "Not unique",
                                        "That area is plain or appears more than once on screen. "
                                        "Mark a bigger or more distinctive area.")
                    return
                step.image = self.add_image(crop, "step")
                step.click_offset = Point(cx - r.x, cy - r.y)
        elif kind == KEY:
            step.keys = "enter"
        dlg = StepDialog(step, self.image(step.image), self)
        if kind in (KEY, TEXT, WAIT) and not dlg.exec():
            return
        at = self.selected() + 1 if self.selected() >= 0 else len(self.flow.steps)
        self.flow.steps.insert(at, step)
        self._refresh_steps(at)

    def edit_step(self):
        i = self.selected()
        if i < 0:
            return
        step = self.flow.steps[i]
        if StepDialog(step, self.image(step.image), self).exec():
            self._refresh_steps(i)

    def move_step(self, delta: int):
        i, j = self.selected(), self.selected() + delta
        if i < 0 or not 0 <= j < len(self.flow.steps):
            return
        steps = self.flow.steps
        steps[i], steps[j] = steps[j], steps[i]
        self._refresh_steps(j)

    def delete_step(self):
        i = self.selected()
        if i >= 0:
            self.flow.steps.pop(i)
            self._refresh_steps(min(i, len(self.flow.steps) - 1))

    # ---------- trying it out ----------

    def _probe(self, i: int, frame):
        step = self.flow.steps[i]
        if step.type not in (CLICK_IMAGE, WAIT_IMAGE, CLICK_POINT):
            return None, f"Step {i + 1}: {step.describe()} (nothing to find)"
        status, rect = probe_step(self.flow, self.all_images(), frame, step)
        text = {vision.FOUND: f"Step {i + 1}: found here",
                vision.MISSING: f"Step {i + 1}: not visible right now",
                vision.AMBIGUOUS: f"Step {i + 1}: found in more than one place!"}[status]
        HighlightOverlay(self.flow.monitor, (frame.shape[1], frame.shape[0]), rect, text,
                         ok=status == vision.FOUND)
        return status, text

    def test_step(self):
        i = self.selected()
        if i < 0:
            QMessageBox.information(self, "Test step", "Select a step first.")
            return
        if not self.need():
            return
        _, text = self._probe(i, self.capture())
        self.say(text)

    def simulate(self):
        if not self.need(anchor=True, steps=True):
            return
        lines = []
        with hidden_windows():
            for i in range(len(self.flow.steps)):
                frame = MssScreen(self.flow.monitor).grab()
                _, text = self._probe(i, frame)
                lines.append(text)
                wait_ms(1300)
        QMessageBox.information(
            self, "Simulation", "\n".join(lines) + "\n\nSteps after the first one usually appear only after "
                                                   "the previous click, so 'not visible' is normal for them here.")

    def run_one(self):
        if self.need(anchor=True, steps=True):
            self.run_controller.start(self.flow, self.all_images(), max_items=1, save_result=False, parent=self)

    # ---------- save / close ----------

    def save(self) -> bool:
        if not self.flow.name:
            QMessageBox.warning(self, "Name missing", "Give the flow a name.")
            return False
        storage.save_flow(self.flow)
        self._saved_state = self.flow.to_dict()
        self.setWindowTitle(f"Edit flow — {self.flow.name}")
        self.saved.emit()
        self.say("Saved.")
        return True

    def closeEvent(self, e):
        if self.flow.to_dict() != self._saved_state:
            answer = QMessageBox.question(self, "Unsaved changes", "Save the changes to this flow?",
                                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save()):
                e.ignore()
                return
            if answer == QMessageBox.Discard and self._saved_state is None:
                storage.delete_flow(self.flow.id)  # a new flow that was never saved
        self.checker.requestInterruption()
        self.checker.wait(2000)
        self.closed.emit()
        super().closeEvent(e)
