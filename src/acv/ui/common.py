"""Small Qt helpers shared by the windows."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ..model import MonitorInfo, Rect


def to_qimage(bgr: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def to_pixmap(bgr: np.ndarray, max_w: int = 0, max_h: int = 0) -> QPixmap:
    pix = QPixmap.fromImage(to_qimage(bgr))
    if max_w and max_h and (pix.width() > max_w or pix.height() > max_h):
        pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pix


def image_label(bgr: np.ndarray | None, max_w: int, max_h: int, empty_text: str = "—") -> QLabel:
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    label.setObjectName("thumb")
    set_label_image(label, bgr, max_w, max_h, empty_text)
    return label


def set_label_image(label: QLabel, bgr: np.ndarray | None, max_w: int, max_h: int, empty_text: str = "—") -> None:
    if bgr is None:
        label.setPixmap(QPixmap())
        label.setText(empty_text)
    else:
        label.setPixmap(to_pixmap(bgr, max_w, max_h))
    label.setMinimumSize(min(max_w, 120), min(max_h, 40))


def qscreen_for(monitor: MonitorInfo):
    """The QScreen showing a monitor (Qt keeps each screen's native top-left as its origin)."""
    screens = QGuiApplication.screens()
    for s in screens:
        g = s.geometry()
        if (g.x(), g.y()) == (monitor.left, monitor.top):
            return s
    for s in screens:
        g, dpr = s.geometry(), s.devicePixelRatio()
        if (round(g.width() * dpr), round(g.height() * dpr)) == (monitor.width, monitor.height):
            return s
    return QGuiApplication.primaryScreen()


def place_on_monitor(widget: QWidget, monitor: MonitorInfo) -> None:
    widget.setGeometry(qscreen_for(monitor).geometry())


def wait_ms(ms: int) -> None:
    """Let the screen repaint (e.g. after hiding our windows) without freezing the UI."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


class HighlightOverlay(QWidget):
    """Click-through overlay that outlines a rectangle on a monitor for a moment."""

    def __init__(self, monitor: MonitorInfo, frame_size: tuple[int, int], rect: Rect | None, text: str,
                 ok: bool = True, ms: int = 1500):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.frame_size, self.rect_, self.text, self.ok = frame_size, rect, text, ok
        place_on_monitor(self, monitor)
        self.show()
        QTimer.singleShot(ms, self.close)

    def paintEvent(self, _):
        p = QPainter(self)
        sx, sy = self.width() / self.frame_size[0], self.height() / self.frame_size[1]
        color = QColor("#16a34a" if self.ok else "#dc2626")
        p.setPen(QPen(color, 4))
        if self.rect_:
            r = self.rect_
            p.drawRect(QRect(int(r.x * sx) - 4, int(r.y * sy) - 4, int(r.w * sx) + 8, int(r.h * sy) + 8))
        p.setFont(self.font())
        box = QRect(self.width() // 2 - 260, 30, 520, 44)
        p.fillRect(box, QColor(20, 20, 20, 220))
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignCenter, self.text)


class hidden_windows:
    """Context manager: hide our windows so the target app is visible, e.g. for a screenshot."""

    def __enter__(self):
        self.windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for w in self.windows:
            w.hide()
        wait_ms(350)
        return self

    def __exit__(self, *exc):
        for w in self.windows:
            w.show()
        return False
