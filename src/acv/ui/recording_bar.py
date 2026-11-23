"""Recording capsule: a black pill at the top of the screen while steps are recorded.

The window is exactly the size of the capsule, so `contains_physical` can tell the
recorder precisely which clicks were on it (they are never recorded).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ..model import MonitorInfo
from . import theme
from .common import qscreen_for
from .widgets import PillButton, animate

COLLAPSED, EXPANDED, HEIGHT, WARN_HEIGHT = 210, 360, 44, 70


class RecordingBar(QWidget):
    undo = Signal()
    finish = Signal()
    recorded = Signal(object)  # emitted from the recorder thread, delivered on the GUI thread

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setWindowTitle("AutoClicker Visual — recording")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFont(theme.font(13, QFont.DemiBold))
        self.physical_rect = (0, 0, 0, 0)
        self._count = 0
        self._pop = 0.0
        self._pulse = 1.0
        self._warning = ""
        self._center_x = 0
        self._top = 0
        self._width = float(EXPANDED)
        self.undo_btn = PillButton("Undo", "glass", self, radius=15)
        self.finish_btn = PillButton("Finish", "filled", self, radius=15)
        self.undo_btn.clicked.connect(self.undo)
        self.finish_btn.clicked.connect(self.finish)
        self._clear_warning = QTimer(self, singleShot=True, interval=5000)
        self._clear_warning.timeout.connect(lambda: self._set_warning(""))
        self._collapse = QTimer(self, singleShot=True, interval=2500)
        self._collapse.timeout.connect(lambda: not self.underMouse() and self._resize_to(COLLAPSED))
        animate(self, "pulse", 1.0, 0.0, 1400, QEasingCurve(QEasingCurve.InOutSine),
                lambda v: (setattr(self, "_pulse", abs(v * 2 - 1)), self.update()), loop=True)
        self._apply_geometry()

    # ---------- placement & geometry ----------

    def place(self, work_monitor: MonitorInfo):
        """Top-centre of another monitor if there is one, otherwise of the work monitor."""
        work = qscreen_for(work_monitor)
        others = [s for s in QApplication.screens() if s is not work]
        geo = (others[0] if others else work).availableGeometry()
        self._center_x, self._top = geo.center().x(), geo.top() + 12
        self._apply_geometry()

    def showEvent(self, e):
        super().showEvent(e)
        self._remember_rect()
        self._collapse.start()  # show the buttons first, then tuck them away

    def _height(self) -> int:
        return WARN_HEIGHT if self._warning else HEIGHT

    def _apply_geometry(self):
        w = round(self._width)
        self.setGeometry(self._center_x - w // 2, self._top, w, self._height())
        expanded = self._width > EXPANDED - 30
        self.undo_btn.setVisible(expanded)
        self.finish_btn.setVisible(expanded)
        y = (HEIGHT - 30) // 2
        self.finish_btn.setGeometry(w - 8 - 72, y, 72, 30)
        self.undo_btn.setGeometry(w - 8 - 72 - 6 - 64, y, 64, 30)
        self._remember_rect()
        self.update()

    def _resize_to(self, width: int):
        animate(self, "width", self._width, float(width), 600, theme.SPRING,
                lambda v: (setattr(self, "_width", v), self._apply_geometry()))

    def enterEvent(self, e):
        self._collapse.stop()
        self._resize_to(EXPANDED)

    def leaveEvent(self, e):
        if not self._warning:
            self._resize_to(COLLAPSED)

    def _remember_rect(self):
        """Physical-pixel rectangle of the capsule, read by the recorder thread to ignore clicks on it."""
        screen = self.screen()
        g, dpr, f = screen.geometry(), screen.devicePixelRatio(), self.frameGeometry()
        self.physical_rect = (round(g.x() + (f.x() - g.x()) * dpr), round(g.y() + (f.y() - g.y()) * dpr),
                              round(f.width() * dpr), round(f.height() * dpr))

    def contains_physical(self, x: int, y: int) -> bool:
        bx, by, bw, bh = self.physical_rect
        return bx <= x < bx + bw and by <= y < by + bh

    # ---------- content ----------

    def set_count(self, n: int):
        if n != self._count:
            self._count = n
            animate(self, "pop", 1.0, 0.0, 400, theme.SMOOTH, lambda v: (setattr(self, "_pop", v), self.update()))
        self.update()

    def warn(self, text: str):
        self._set_warning(text)
        self._clear_warning.start()
        self._resize_to(EXPANDED)

    def _set_warning(self, text: str):
        self._warning = text
        self._apply_geometry()
        if not text and not self.underMouse():
            self._resize_to(COLLAPSED)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, min(r.height() / 2, 22), min(r.height() / 2, 22))
        red = theme.color(theme.DANGER)
        red.setAlphaF(0.35 + 0.65 * self._pulse)
        p.setBrush(red)
        p.drawEllipse(QPointF(20, HEIGHT / 2), 5, 5)
        p.setFont(self.font())
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(34, 0, 100, HEIGHT), Qt.AlignVCenter | Qt.AlignLeft, "Recording")
        x = 34 + QFontMetrics(self.font()).horizontalAdvance("Recording") + 10
        num = str(self._count)
        p.save()
        p.translate(x + 5, HEIGHT / 2 - 3 * self._pop)
        p.scale(1 + 0.15 * self._pop, 1 + 0.15 * self._pop)
        p.drawText(QRectF(-10, -HEIGHT / 2, 20, HEIGHT), Qt.AlignCenter, num)
        p.restore()
        p.setPen(QColor(255, 255, 255, 160))
        p.setFont(theme.font(13))
        p.drawText(QRectF(x + 14, 0, 60, HEIGHT), Qt.AlignVCenter | Qt.AlignLeft, "step" if self._count == 1 else "steps")
        if self._warning:
            p.setPen(QColor("#ffcf7a"))
            p.setFont(theme.font(12))
            p.drawText(QRectF(18, HEIGHT - 6, r.width() - 36, WARN_HEIGHT - HEIGHT), Qt.AlignLeft | Qt.AlignTop,
                       QFontMetrics(p.font()).elidedText(self._warning, Qt.ElideRight, int(r.width() - 36)))
