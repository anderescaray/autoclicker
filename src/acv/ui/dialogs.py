"""Smaller dialogs: monitor choice, step editing, run options and run problems."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout,
)

from .. import engine
from ..desktop import MssScreen, parse_keys
from ..model import CLICK_IMAGE, CLICK_POINT, IMAGE_STEPS, KEY, STEP_TYPE_NAMES, TEXT, WAIT, MonitorInfo, Step
from .common import image_label, to_pixmap


class MonitorDialog(QDialog):
    """Pick the work monitor by clicking its thumbnail."""

    def __init__(self, monitors: list[MonitorInfo], current: int | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose the work monitor")
        self.choice: MonitorInfo | None = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click the monitor where the list you want to process is shown."))
        row = QHBoxLayout()
        for m in monitors:
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            pix = to_pixmap(MssScreen(m).grab(), 320, 200)
            btn.setIcon(pix)
            btn.setIconSize(pix.size())
            btn.setText(f"Monitor {m.index}  ·  {m.width}×{m.height}  ·  {round(m.scale * 100)} %")
            btn.setCheckable(True)
            btn.setChecked(m.index == current)
            btn.clicked.connect(lambda _=False, m=m: self._choose(m))
            row.addWidget(btn)
        lay.addLayout(row)

    def _choose(self, m: MonitorInfo):
        self.choice = m
        self.accept()


class StepDialog(QDialog):
    """Edit one step's parameters. Fields shown depend on the step type."""

    def __init__(self, step: Step, image=None, parent=None):
        super().__init__(parent)
        self.step = step
        self.setWindowTitle(f"Edit step — {STEP_TYPE_NAMES[step.type]}")
        form = QFormLayout()
        self.label = QLineEdit(step.label)
        form.addRow("Label", self.label)
        if image is not None:
            form.addRow("Target", image_label(image, 360, 160))
        self.button = QComboBox()
        self.button.addItems(["Left", "Right"])
        self.button.setCurrentIndex(1 if step.button == "right" else 0)
        self.clicks = QComboBox()
        self.clicks.addItems(["Single click", "Double click"])
        self.clicks.setCurrentIndex(1 if step.clicks == 2 else 0)
        self.confidence = _dspin(step.confidence, 0.5, 0.99, 0.01, 2)
        self.timeout = _dspin(step.timeout_s, 1, 600, 1, 0, " s")
        self.delay = _dspin(step.delay_after_s, 0, 60, 0.1, 1, " s")
        self.px, self.py = _ispin(step.point.x), _ispin(step.point.y)
        self.keys = QLineEdit(step.keys)
        self.keys.setPlaceholderText("e.g. enter, f5, ctrl+s")
        self.text = QLineEdit(step.text)
        self.seconds = _dspin(step.seconds, 0.1, 3600, 0.5, 1, " s")

        t = step.type
        if t in (CLICK_IMAGE, CLICK_POINT):
            form.addRow("Mouse button", self.button)
            form.addRow("Click", self.clicks)
        if t == CLICK_POINT:
            row = QHBoxLayout()
            row.addWidget(QLabel("x"))
            row.addWidget(self.px)
            row.addWidget(QLabel("y"))
            row.addWidget(self.py)
            form.addRow("Position from anchor", row)
        if t in IMAGE_STEPS:
            form.addRow("Match confidence", self.confidence)
            form.addRow("Wait for it up to", self.timeout)
        if t == KEY:
            form.addRow("Key or combination", self.keys)
        if t == TEXT:
            form.addRow("Text to type", self.text)
        if t == WAIT:
            form.addRow("Wait", self.seconds)
        else:
            form.addRow("Pause afterwards", self.delay)

        self.error = QLabel()
        self.error.setObjectName("error")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addWidget(buttons)

    def _ok(self):
        s = self.step
        if s.type == KEY:
            try:
                parse_keys(self.keys.text())
            except ValueError as e:
                self.error.setText(str(e))
                return
        s.label = self.label.text().strip()
        s.button = "right" if self.button.currentIndex() == 1 else "left"
        s.clicks = 2 if self.clicks.currentIndex() == 1 else 1
        s.confidence = self.confidence.value()
        s.timeout_s = self.timeout.value()
        s.delay_after_s = self.delay.value()
        s.point.x, s.point.y = self.px.value(), self.py.value()
        s.keys = self.keys.text().strip().lower()
        s.text = self.text.text()
        s.seconds = self.seconds.value()
        self.accept()


class RunDialog(QDialog):
    """Options asked right before a run."""

    def __init__(self, flow, parent=None):
        super().__init__(parent)
        self.flow = flow
        self.setWindowTitle(f"Run — {flow.name}")
        form = QFormLayout()
        self.max_items = QSpinBox()
        self.max_items.setRange(1, 100000)
        self.max_items.setValue(flow.run.max_items)
        self.maximize = QCheckBox("Maximise the target window before starting")
        self.maximize.setChecked(flow.run.maximize_window)
        form.addRow("Process at most", self.max_items)
        form.addRow("", self.maximize)
        hint = QLabel("Don't touch the mouse while it runs. Press <b>F12</b> at any time to stop.")
        hint.setWordWrap(True)
        buttons = QDialogButtonBox()
        buttons.addButton("Start", QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(buttons)

    def _ok(self):
        self.flow.run.max_items = self.max_items.value()
        self.flow.run.maximize_window = self.maximize.isChecked()
        self.accept()


RELOCATE = "relocate"
_PROBLEM_BUTTONS = {
    engine.ANCHOR_MISSING: [("Retry", engine.RETRY), ("Show where it is…", RELOCATE), ("Cancel", engine.STOP)],
    engine.ROW_OFFSCREEN: [("Retry", engine.RETRY), ("Show where it is…", RELOCATE), ("Stop", engine.STOP)],
    engine.STEP_MISSING: [("Retry step", engine.RETRY), ("Stop", engine.STOP)],
    engine.STEP_AMBIGUOUS: [("Retry step", engine.RETRY), ("Stop", engine.STOP)],
    engine.LIST_UNCHANGED: [("Wait again", engine.RETRY), ("Stop", engine.STOP)],
    engine.USER_MOUSE: [("Continue", engine.RETRY), ("Stop", engine.STOP)],
}
_PROBLEM_HELP = {
    engine.ANCHOR_MISSING: "Make sure the window with the list is visible and not covered, then retry.",
    engine.ROW_OFFSCREEN: "The window may have moved or shrunk. Retry, or mark the list again.",
    engine.STEP_MISSING: "Nothing has been clicked since. Bring the expected window to the front and retry.",
    engine.STEP_AMBIGUOUS: "Several places look the same, so nothing was clicked. Retry or record the step again.",
    engine.LIST_UNCHANGED: "The first item is still there, so it won't be processed twice. "
                           "If the list needs a refresh, add a 'Press key F5' step.",
    engine.USER_MOUSE: "Put the mouse down and choose Continue when you are ready.",
}


class ProblemDialog(QDialog):
    """'What I was looking for' vs 'What I see now', with concrete actions. self.answer holds the choice."""

    def __init__(self, problem: engine.Problem, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AutoClicker Visual — paused")
        self.answer = engine.STOP
        lay = QVBoxLayout(self)
        title = QLabel(problem.message)
        title.setObjectName("title")
        title.setWordWrap(True)
        lay.addWidget(title)
        hint = QLabel(_PROBLEM_HELP.get(problem.kind, ""))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        if problem.expected is not None or problem.screen is not None:
            grid = QGridLayout()
            if problem.expected is not None:
                box = QGroupBox("What I was looking for")
                QVBoxLayout(box).addWidget(image_label(problem.expected, 320, 240))
                grid.addWidget(box, 0, 0)
            if problem.screen is not None:
                box = QGroupBox("What I see now")
                QVBoxLayout(box).addWidget(image_label(problem.screen, 640, 400))
                grid.addWidget(box, 0, 1)
            lay.addLayout(grid)
        row = QHBoxLayout()
        row.addStretch()
        for text, answer in _PROBLEM_BUTTONS.get(problem.kind, [("Stop", engine.STOP)]):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, a=answer: self._answer(a))
            row.addWidget(btn)
        lay.addLayout(row)

    def _answer(self, answer: str):
        self.answer = answer
        self.accept()


def _dspin(value, lo, hi, step, decimals, suffix=""):
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setValue(value)
    return spin


def _ispin(value):
    spin = QSpinBox()
    spin.setRange(-10000, 10000)
    spin.setValue(value)
    return spin
