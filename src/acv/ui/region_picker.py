"""Full-screen, snipping-tool-like overlay to mark rectangles on a frozen screenshot."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..model import MonitorInfo, Rect
from . import theme
from .common import place_on_monitor, to_qimage



class RegionPicker(QWidget):
    """Shows `frame` dimmed over the monitor and asks for one rectangle per prompt.

    Esc goes back one rectangle (or cancels on the first one). Rectangles are in frame pixels.
    """

    def __init__(self, frame: np.ndarray, monitor: MonitorInfo, prompts: list[str], group: _Group | None = None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.monitor = monitor
        self.group = group
        self._silent = False
        self.frame = frame
        self.image = to_qimage(frame)
        self.prompts = prompts
        self.rects: list[Rect] = []
        self.result: list[Rect] | None = None
        self._start: QPoint | None = None
        self._current: QRect | None = None
        self._loop = group.loop if group else QEventLoop()
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
            if self.group:
                self.group.claim(self)  # the list is on this monitor: close the others
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
        if self.group:
            self.group.finish(self)
        self.close()
        self._loop.quit()

    def closeEvent(self, e):
        if not self._silent:
            self._loop.quit()
        super().closeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(self.rect(), self.image)
        p.fillRect(self.rect(), QColor(10, 14, 24, 120))
        boxes = [self._to_widget(r) for r in self.rects] + ([self._current] if self._current else [])
        sx, sy = self._scale()
        accent = theme.color(theme.ACCENT)
        for box in boxes:
            # show the real screen inside each marked box, undimmed
            src = QRect(round(box.x() * sx), round(box.y() * sy), round(box.width() * sx), round(box.height() * sy))
            p.drawImage(box, self.image, src)
            tint = QColor(accent)
            tint.setAlphaF(0.10)
            p.setBrush(tint)
            p.setPen(QPen(accent, 2))
            p.drawRoundedRect(QRectF(box), 4, 4)
        step = min(len(self.rects), len(self.prompts) - 1)
        lead = f"Step {step + 1} of {len(self.prompts)}   " if len(self.prompts) > 1 else ""
        bold = theme.font(14, QFont.DemiBold)
        small = theme.font(12)
        width = min(self.width() - 40, QFontMetrics(bold).horizontalAdvance(lead + self.prompts[step]) + 64)
        pill = QRectF((self.width() - width) / 2, 22, width, 62)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 235))
        p.drawRoundedRect(pill, 22, 22)
        p.setFont(bold)
        p.setPen(QColor("#ffffff"))
        line = QRectF(pill.x() + 24, pill.y() + 10, pill.width() - 48, 24)
        if lead:
            p.setPen(QColor(255, 255, 255, 140))
            p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter, lead)
            line.setLeft(line.left() + QFontMetrics(bold).horizontalAdvance(lead))
            p.setPen(QColor("#ffffff"))
        p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(bold).elidedText(self.prompts[step], Qt.ElideRight, int(line.width())))
        p.setFont(small)
        p.setPen(QColor(255, 255, 255, 140))
        p.drawText(QRectF(pill.x() + 24, pill.y() + 34, pill.width() - 48, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "Esc or right-click: go back")


class _Group:
    """Pickers shown on several monitors at once; the first one the user drags on wins."""

    def __init__(self):
        self.loop = QEventLoop()
        self.pickers: list[RegionPicker] = []

    def claim(self, winner: RegionPicker) -> None:
        for p in self.pickers:
            if p is not winner:
                p._silent = True
                p.close()
        self.pickers = [winner]

    def finish(self, picker: RegionPicker) -> None:
        if picker.result is None:  # cancelled: close every picker
            self.claim(picker)


def pick_regions(frame: np.ndarray, monitor: MonitorInfo, prompts: list[str]) -> list[Rect] | None:
    return RegionPicker(frame, monitor, prompts).exec()


def pick_regions_anywhere(frames: list[tuple[MonitorInfo, np.ndarray]], prompts: list[str]):
    """Show a picker on every monitor. Returns (monitor, frame, rects) for the one used, or None."""
    if len(frames) == 1:
        mon, frame = frames[0]
        rects = pick_regions(frame, mon, prompts)
        return (mon, frame, rects) if rects else None
    group = _Group()
    group.pickers = [RegionPicker(frame, mon, prompts, group) for mon, frame in frames]
    for p in group.pickers:
        p.show()
        p.raise_()
    group.pickers[0].activateWindow()
    group.loop.exec()
    winner = group.pickers[0] if group.pickers else None
    if winner is None or not winner.result:
        return None
    return winner.monitor, winner.frame, winner.result


def mark_list(frames: list[tuple[MonitorInfo, np.ndarray]], parent=None):
    """Ask for the anchor and the first row, on whichever monitor shows the list.

    `frames` holds one screenshot per monitor. Returns (monitor, anchor_image, row_offset, row_image)
    or None if cancelled. The row offset is relative to the anchor, so it follows the window when it moves.
    """
    from PySide6.QtWidgets import QMessageBox

    from .. import vision

    prompts = ["On the screen with the list, drag to mark the ANCHOR — something that never changes, e.g. its header.",
               "Now drag to mark the FIRST ROW of the list (with an item in it, without the header)."]
    while True:
        picked = pick_regions_anywhere(frames, prompts)
        if not picked:
            return None
        monitor, frame, (a, r) = picked
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
            return monitor, anchor, Rect(r.x - a.x, r.y - a.y, r.w, r.h), row
        QMessageBox.warning(parent, "Mark again", problem)
