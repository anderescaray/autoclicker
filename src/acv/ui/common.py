"""Small Qt helpers shared by the windows."""

from __future__ import annotations

import logging
import time

import numpy as np
import shiboken6
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ..model import MonitorInfo, Rect
from . import theme
from .widgets import animate


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
    """Click-through overlay: a rounded accent outline around a target and a label above it, fading in and out."""

    def __init__(self, monitor: MonitorInfo, frame_size: tuple[int, int], rect: Rect | None, text: str,
                 ok: bool = True, ms: int = 1500):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.frame_size, self.rect_, self.text, self.ok = frame_size, rect, text, ok
        self._o = 0.0
        place_on_monitor(self, monitor)
        self.show()
        setter = lambda v: (setattr(self, "_o", v), self.update())  # noqa: E731
        animate(self, "fade", 0.0, 1.0, 200, theme.SMOOTH, setter)
        QTimer.singleShot(ms, self, lambda: animate(self, "fade", self._o, 0.0, 300, theme.SMOOTH, setter,
                                                     on_done=self.close))

    def paintEvent(self, _):
        t = theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._o)
        sx, sy = self.width() / self.frame_size[0], self.height() / self.frame_size[1]
        color = t.color(t.ACCENT if self.ok else t.WARN)
        label_at = QPoint(self.width() // 2, 40)
        if self.rect_:
            r = self.rect_
            box = QRectF(r.x * sx - 5, r.y * sy - 5, r.w * sx + 10, r.h * sy + 10)
            for width, alpha in ((12, 0.10), (7, 0.18)):
                glow = QColor(color)
                glow.setAlphaF(alpha)
                p.setPen(QPen(glow, width))
                p.drawRoundedRect(box, 8, 8)
            p.setPen(QPen(color, 3))
            p.drawRoundedRect(box, 8, 8)
            label_at = QPoint(round(box.center().x()), max(22, round(box.top()) - 22))
        p.setFont(t.font(13, QFont.DemiBold))
        fm = QFontMetrics(p.font())
        w = fm.horizontalAdvance(self.text) + 28
        pill = QRectF(label_at.x() - w / 2, label_at.y() - 15, w, 30)
        pill.moveLeft(max(8, min(pill.left(), self.width() - w - 8)))
        p.setPen(Qt.NoPen)
        p.setBrush(t.color(t.SNACK))
        p.drawRoundedRect(pill, 15, 15)
        p.setPen(QColor("white"))
        p.drawText(pill, Qt.AlignCenter, self.text)


def visible_windows() -> list[QWidget]:
    """Our visible top-level windows, except click-through overlays that close themselves."""
    return [w for w in QApplication.topLevelWidgets()
            if w.isVisible() and not w.windowFlags() & Qt.WindowTransparentForInput]


def close_overlays() -> None:
    """Remove highlight overlays at once, so a screenshot never contains them."""
    for w in QApplication.topLevelWidgets():
        if isinstance(w, HighlightOverlay) and shiboken6.isValid(w):
            w.close()


def show_again(windows: list[QWidget]) -> None:
    for w in windows:
        if shiboken6.isValid(w):  # a window may have been deleted while hidden
            w.show()


class hidden_windows:
    """Context manager: hide our windows so the target app is visible, e.g. for a screenshot."""

    def __enter__(self):
        close_overlays()
        self.windows = visible_windows()
        for w in self.windows:
            w.hide()
        wait_ms(350)
        return self

    def __exit__(self, *exc):
        show_again(self.windows)
        return False


def fit_pixmap(bgr: np.ndarray, w: int, h: int) -> QPixmap:
    """Pixmap that shows at most w×h logical pixels, sharp on high-DPI screens and never upscaled."""
    pix = to_pixmap(bgr, 2 * w, 2 * h)
    pix.setDevicePixelRatio(max(1.0, pix.width() / w, pix.height() / h))
    return pix


def grab_monitors() -> list[tuple[MonitorInfo, np.ndarray]]:
    """A screenshot of every monitor (empty if the system can't report them)."""
    from ..desktop import MssScreen, list_monitors
    try:
        return [(m, MssScreen(m).grab()) for m in list_monitors()]
    except Exception:
        logging.getLogger(__name__).exception("Cannot capture the monitors")
        return []


def find_on_monitors(template: np.ndarray, confidence: float, prefer: int | None = None):
    """The monitor where `template` appears exactly once (trying monitor `prefer` first), or None."""
    from .. import vision
    shots = grab_monitors()
    shots.sort(key=lambda mf: mf[0].index != prefer)
    for mon, frame in shots:
        if vision.locate(frame, template, confidence)[0] == vision.FOUND:
            return mon
    return None
