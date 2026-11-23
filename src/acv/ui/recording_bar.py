"""Small always-on-top bar shown while recording steps."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..model import MonitorInfo
from .common import qscreen_for


class RecordingBar(QWidget):
    undo = Signal()
    finish = Signal()
    recorded = Signal(object)  # emitted from the recorder thread, delivered on the GUI thread

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AutoClicker Visual — recording")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.label = QLabel()
        self.label.setObjectName("recording")
        undo = QPushButton("Undo last")
        undo.clicked.connect(self.undo)
        done = QPushButton("Finish")
        done.setObjectName("primary")
        done.clicked.connect(self.finish)
        row.addWidget(self.label, 1)
        row.addWidget(undo)
        row.addWidget(done)
        lay.addLayout(row)
        self.hint = QLabel("Do the clicks for ONE item in the target app, as you normally would.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.setFixedWidth(460)
        self.physical_rect = (0, 0, 0, 0)

    def place(self, work_monitor: MonitorInfo):
        """Top-centre of another monitor if there is one, otherwise top-centre of the work monitor."""
        work = qscreen_for(work_monitor)
        others = [s for s in QApplication.screens() if s is not work]
        geo = (others[0] if others else work).availableGeometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2, geo.top() + 40)

    def _remember_rect(self):
        """Physical-pixel rectangle of the bar, read by the recorder thread to ignore clicks on it."""
        screen = self.screen()
        g, dpr, f = screen.geometry(), screen.devicePixelRatio(), self.frameGeometry()
        self.physical_rect = (round(g.x() + (f.x() - g.x()) * dpr), round(g.y() + (f.y() - g.y()) * dpr),
                              round(f.width() * dpr), round(f.height() * dpr))

    def showEvent(self, e):
        super().showEvent(e)
        self._remember_rect()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._remember_rect()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._remember_rect()

    def contains_physical(self, x: int, y: int) -> bool:
        bx, by, bw, bh = self.physical_rect
        return bx <= x < bx + bw and by <= y < by + bh

    def set_count(self, n: int):
        self.label.setText(f"● Recording — {n} step{'s' if n != 1 else ''}")

    def warn(self, text: str):
        self.hint.setText(f"⚠ {text}")
        self.hint.setObjectName("warning")
        self.hint.setStyleSheet("color: #b45309;")
        QTimer.singleShot(5000, self, lambda: (self.hint.setStyleSheet(""),
                                         self.hint.setText("Keep going, or press Finish when the item is done.")))
