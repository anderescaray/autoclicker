"""Full-screen, snipping-tool-like overlay to mark rectangles on a frozen screenshot."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..model import MonitorInfo, Rect
from .common import place_on_monitor, to_qimage

COLORS = ["#f59e0b", "#22c55e", "#3b82f6"]


class RegionPicker(QWidget):
    """Shows `frame` dimmed over the monitor and asks for one rectangle per prompt.

    Esc goes back one rectangle (or cancels on the first one). Rectangles are in frame pixels.
    """

    def __init__(self, frame: np.ndarray, monitor: MonitorInfo, prompts: list[str]):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.frame = frame
        self.image = to_qimage(frame)
        self.prompts = prompts
        self.rects: list[Rect] = []
        self.result: list[Rect] | None = None
        self._start: QPoint | None = None
        self._current: QRect | None = None
        self._loop = QEventLoop()
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        place_on_monitor(self, monitor)

    def exec(self) -> list[Rect] | None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._loop.exec()
        return self.result

    # --- coordinates: widget (logical) <-> frame (physical pixels) ---

    def _scale(self) -> tuple[float, float]:
        return self.frame.shape[1] / self.width(), self.frame.shape[0] / self.height()

    def _to_frame(self, r: QRect) -> Rect:
        sx, sy = self._scale()
        return Rect(round(r.x() * sx), round(r.y() * sy), round(r.width() * sx), round(r.height() * sy))

    def _to_widget(self, r: Rect) -> QRect:
        sx, sy = self._scale()
        return QRect(round(r.x / sx), round(r.y / sy), round(r.w / sx), round(r.h / sy))

    # --- events ---

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.position().toPoint()
            self._current = QRect(self._start, self._start)
        elif e.button() == Qt.RightButton:
            self._back()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._current = QRect(self._start, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._start is None:
            return
        rect = self._to_frame(self._current)
        self._start = self._current = None
        if rect.w < 4 or rect.h < 4:  # a stray click, not a drag
            self.update()
            return
        self.rects.append(rect)
        if len(self.rects) == len(self.prompts):
            self._finish(self.rects)
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._back()

    def _back(self):
        if self.rects:
            self.rects.pop()
            self.update()
        else:
            self._finish(None)

    def _finish(self, result):
        self.result = result
        self.close()
        self._loop.quit()

    def closeEvent(self, e):
        self._loop.quit()
        super().closeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        boxes = [self._to_widget(r) for r in self.rects] + ([self._current] if self._current else [])
        for i, box in enumerate(boxes):
            # show the real screen inside each marked box, undimmed
            sx, sy = self._scale()
            src = QRect(round(box.x() * sx), round(box.y() * sy), round(box.width() * sx), round(box.height() * sy))
            p.drawImage(box, self.image, src)
            p.setPen(QPen(QColor(COLORS[i % len(COLORS)]), 2))
            p.drawRect(box)
        step = min(len(self.rects), len(self.prompts) - 1)
        prefix = f"Step {step + 1}/{len(self.prompts)}:  " if len(self.prompts) > 1 else ""
        text = f"{prefix}{self.prompts[step]}\nEsc or right-click: go back"
        font = QFont(self.font())
        font.setPointSize(13)
        p.setFont(font)
        width = min(self.width() - 40, p.fontMetrics().horizontalAdvance(prefix + self.prompts[step]) + 60)
        box = QRect((self.width() - width) // 2, 24, width, p.fontMetrics().height() * 2 + 24)
        p.fillRect(box, QColor(17, 24, 39, 235))
        p.setPen(QColor(COLORS[step % len(COLORS)]))
        p.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, text)


def pick_regions(frame: np.ndarray, monitor: MonitorInfo, prompts: list[str]) -> list[Rect] | None:
    return RegionPicker(frame, monitor, prompts).exec()


def mark_list(frame: np.ndarray, monitor: MonitorInfo, parent=None):
    """Ask for the anchor and the first row on `frame`.

    Returns (anchor_image, row_offset, row_image) or None if cancelled.
    The row offset is relative to the anchor, so it follows the window when it moves.
    """
    from PySide6.QtWidgets import QMessageBox

    from .. import vision

    prompts = ["Drag to mark the ANCHOR — something that always looks the same, e.g. the list's header.",
               "Now drag to mark the FIRST ROW of the list (with an item in it, without the header)."]
    while True:
        rects = pick_regions(frame, monitor, prompts)
        if not rects:
            return None
        a, r = rects
        anchor = vision.crop(frame, a)
        row = vision.crop(frame, r)
        problem = None
        if not vision.has_detail(anchor):
            problem = "The anchor is a plain area. Mark something with text or a distinctive shape."
        elif vision.locate(frame, anchor, 0.85)[0] != vision.FOUND:
            problem = "The anchor appears more than once on screen. Mark a bigger or more distinctive area."
        elif vision.row_score(row) < vision.MIN_ROW_SCORE * 2:
            problem = "The first row looks empty. Mark it while it contains an item."
        if problem is None:
            return anchor, Rect(r.x - a.x, r.y - a.y, r.w, r.h), row
        QMessageBox.warning(parent, "Mark again", problem)
