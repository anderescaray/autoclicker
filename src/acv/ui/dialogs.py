"""Dialogs: step editing and run problems."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout,
)

from .. import engine
from ..desktop import parse_keys
from ..model import CLICK_IMAGE, CLICK_POINT, IMAGE_STEPS, KEY, STEP_TYPE_NAMES, TEXT, WAIT, Step
from . import theme
from .common import fit_pixmap, image_label
from .widgets import PillButton, WarnIcon, animate


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


RELOCATE = "relocate"
_PROBLEM_BUTTONS = {
    engine.ANCHOR_MISSING: [("Try again", engine.RETRY), ("Show where it is", RELOCATE), ("Cancel", engine.STOP)],
    engine.ROW_OFFSCREEN: [("Try again", engine.RETRY), ("Show where it is", RELOCATE), ("Stop", engine.STOP)],
    engine.STEP_MISSING: [("Try again", engine.RETRY), ("Stop", engine.STOP)],
    engine.STEP_AMBIGUOUS: [("Try again", engine.RETRY), ("Stop", engine.STOP)],
    engine.LIST_UNCHANGED: [("Wait again", engine.RETRY), ("Stop", engine.STOP)],
    engine.USER_MOUSE: [("Continue", engine.RETRY), ("Stop", engine.STOP)],
}
_PROBLEM_HELP = {
    engine.ANCHOR_MISSING: "Make sure the window with the list is visible and not covered, then try again.",
    engine.ROW_OFFSCREEN: "The window may have moved or shrunk. Try again, or mark the list again.",
    engine.STEP_MISSING: "Nothing has been clicked since. Bring the expected window to the front and try again.",
    engine.STEP_AMBIGUOUS: "Several places look the same, so nothing was clicked. Try again or record the step again.",
    engine.LIST_UNCHANGED: "The first item is still there, so it won't be processed twice. "
                           "If the list needs a refresh, add a 'Press key F5' step.",
    engine.USER_MOUSE: "Put the mouse down and choose Continue when you are ready.",
}


class ProblemDialog(QDialog):
    """Alert card: 'Looking for' vs 'On screen now', with concrete actions. self.answer holds the choice."""

    def __init__(self, problem: engine.Problem, parent=None):
        super().__init__(parent, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Dialog)
        self.setWindowTitle("AutoClicker Visual — paused")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.answer = engine.STOP
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 30)  # room for the shadow
        card = QFrame()
        card.setObjectName("card")
        card.setGraphicsEffect(QGraphicsDropShadowEffect(card, blurRadius=44, offset=QPointF(0, 14),
                                                         color=QColor(15, 22, 40, 80)))
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 22, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(WarnIcon(), 0, Qt.AlignHCenter)
        title = QLabel(problem.message)
        title.setFont(theme.font(16, QFont.Bold, display=True))
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        lay.addWidget(title)
        hint = QLabel(_PROBLEM_HELP.get(problem.kind, ""))
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        if problem.expected is not None or problem.screen is not None:
            row = QHBoxLayout()
            row.setSpacing(12)
            for img, text, w, h in ((problem.expected, "Looking for", 220, 150), (problem.screen, "On screen now", 420, 260)):
                if img is None:
                    continue
                col = QVBoxLayout()
                col.setSpacing(5)
                pic = QLabel()
                pic.setObjectName("thumb")
                pic.setAlignment(Qt.AlignCenter)
                pic.setPixmap(fit_pixmap(img, w, h))
                cap = QLabel(text)
                cap.setObjectName("hint")
                col.addWidget(pic)
                col.addWidget(cap)
                col.addStretch(1)
                row.addLayout(col)
            lay.addSpacing(4)
            lay.addLayout(row)
        lay.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        choices = _PROBLEM_BUTTONS.get(problem.kind, [("Stop", engine.STOP)])
        for text, answer in reversed(choices):  # the main action goes last, on the right
            btn = PillButton(text, "filled" if answer == engine.RETRY else "plain")
            btn.clicked.connect(lambda _=False, a=answer: self._answer(a))
            buttons.addWidget(btn, 1)
        lay.addLayout(buttons)

    def showEvent(self, e):
        super().showEvent(e)
        geo = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self.adjustSize()
        end = QPoint(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        self.setWindowOpacity(0.0)
        animate(self, "fade", 0.0, 1.0, 250, theme.SMOOTH, self.setWindowOpacity)
        animate(self, "rise", 14.0, 0.0, 550, theme.SPRING, lambda v: self.move(end.x(), end.y() + round(v)))

    def _answer(self, answer: str):
        self.answer = answer
        self.accept()


def _dspin(value, lo, hi, step, decimals, suffix=""):
    spin = QDoubleSpinBox()
    spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
    spin.setRange(lo, hi)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setValue(value)
    return spin


def _ispin(value):
    spin = QSpinBox()
    spin.setButtonSymbols(QSpinBox.NoButtons)
    spin.setRange(-10000, 10000)
    spin.setValue(value)
    return spin
