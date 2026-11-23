"""Custom-painted widgets and list delegates (docs/design/ui-spec.md §3-4).

Stylesheets can't animate or scale, so these paint themselves and animate a float
property with QVariantAnimation. Colours, radii and timings come from theme.py.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import (
    QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QListWidget, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout,
    QWidget,
)

from . import theme


def animate(owner, key: str, start: float, end: float, ms: int, curve: QEasingCurve, setter, loop: bool = False,
            on_done=None):
    """Run (or restart) the animation `key` of `owner`; jump to the end when animations are off."""
    old = owner.__dict__.get("_anims", {}).get(key)
    if old is not None:
        old.stop()
    if not theme.animations() or ms <= 0:
        setter(end)
        if on_done:
            on_done()
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(curve)
    anim.valueChanged.connect(setter)
    if loop:
        anim.setLoopCount(-1)
    if on_done:
        anim.finished.connect(on_done)
    owner.__dict__.setdefault("_anims", {})[key] = anim
    anim.start()
    return anim


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t, a.alphaF() + (b.alphaF() - a.alphaF()) * t)


class PillButton(QPushButton):
    """Rounded button that shrinks when pressed and springs back. variant: plain, tonal, filled, danger, glass."""

    def __init__(self, text: str = "", variant: str = "plain", parent=None, *, play: bool = False,
                 dot: bool = False, large: bool = False, radius: float | None = None):
        super().__init__(text, parent)
        self.variant, self.play, self.dot, self.large, self.radius = variant, play, dot, large, radius
        self._scale = 1.0
        self._pulse = 1.0
        self._kbd_focus = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(theme.font(14 if large else 13, QFont.DemiBold))
        self.setAttribute(Qt.WA_Hover)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        extra = 17 if (self.play or self.dot) else 0
        return QSize(fm.horizontalAdvance(self.text()) + (40 if self.large else 28) + extra, 36 if self.large else 30)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_recording(self, on: bool) -> None:
        if on:
            animate(self, "pulse", 1.0, 0.0, 1400, QEasingCurve(QEasingCurve.InOutSine), self._set_pulse, loop=True)
        else:
            animate(self, "pulse", self._pulse, 1.0, 0, theme.SMOOTH, self._set_pulse)

    def _set_pulse(self, v):
        self._pulse = abs(v * 2 - 1) if 0 <= v <= 1 else 1.0
        self.update()

    def _set_scale(self, v):
        self._scale = v
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            animate(self, "press", self._scale, 0.95, 80, QEasingCurve(QEasingCurve.Linear), self._set_scale)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        animate(self, "press", self._scale, 1.0, 400, theme.SPRING, self._set_scale)
        super().mouseReleaseEvent(e)

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def _colors(self) -> tuple[QColor, QColor]:
        hover, down = self.underMouse(), self.isDown()
        v = self.variant
        if v == "filled":
            return theme.color(theme.ACCENT_HOVER if hover else theme.ACCENT), QColor("#ffffff")
        if v == "danger":
            return theme.color(theme.DANGER).lighter(108 if hover else 100), QColor("#ffffff")
        if v == "tonal":
            return theme.color(theme.ACCENT, 0.16 if hover else 0.10), theme.color(theme.ACCENT_TEXT)
        if v == "glass":
            return QColor(255, 255, 255, 52 if hover else 36), QColor("#ffffff")
        bg = theme.FILL_STRONG if down else theme.FILL_HOVER if hover else theme.FILL
        return theme.color(bg), theme.color(theme.TEXT)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        bg, fg = self._colors()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        c = r.center()
        p.translate(c)
        p.scale(self._scale, self._scale)
        p.translate(-c)
        radius = self.radius if self.radius is not None else theme.R_PILL
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, radius, radius)
        if self._kbd_focus:
            p.setPen(QPen(theme.color(theme.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)
        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        icon = 17 if (self.play or self.dot) else 0
        x = (self.width() - tw - icon) / 2
        cy = self.height() / 2
        if self.play:
            p.setPen(Qt.NoPen)
            p.setBrush(fg)
            p.drawPolygon(QPolygonF([QPointF(x + 1, cy - 5), QPointF(x + 10, cy), QPointF(x + 1, cy + 5)]))
        elif self.dot:
            p.setPen(Qt.NoPen)
            dot = theme.color(theme.DANGER)
            dot.setAlphaF(0.3 + 0.7 * self._pulse)
            p.setBrush(dot)
            p.drawEllipse(QPointF(x + 4, cy), 4, 4)
        p.setPen(fg)
        p.setFont(self.font())
        p.drawText(QRectF(x + icon, 0, tw + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class RoundButton(PillButton):
    """30 px circular icon button (+, ?) used in the sidebar."""

    def __init__(self, glyph: str, tooltip: str, parent=None):
        super().__init__("", "plain", parent, radius=15)
        self.glyph = glyph
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(30, 30)

    def sizeHint(self) -> QSize:
        return QSize(30, 30)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QRectF(self.rect()).center()
        p.translate(c)
        p.scale(self._scale, self._scale)
        p.setPen(QPen(theme.color(theme.TEXT), 2, Qt.SolidLine, Qt.RoundCap))
        if self.glyph == "+":
            p.drawLine(QPointF(-6, 0), QPointF(6, 0))
            p.drawLine(QPointF(0, -6), QPointF(0, 6))
        else:
            p.setFont(theme.font(14, QFont.Bold))
            p.drawText(QRectF(-15, -15, 30, 30), Qt.AlignCenter, self.glyph)


class Switch(QAbstractButton):
    """iOS/macOS-style switch with a springy knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self.toggled.connect(lambda on: animate(self, "knob", self._pos, 1.0 if on else 0.0, 400, theme.SPRING,
                                                self._set_pos))

    def setChecked(self, on: bool) -> None:  # set from code: jump; clicked by the user: animate
        super().setChecked(on)
        anim = self.__dict__.get("_anims", {}).get("knob")
        if anim is not None:
            anim.stop()
        self._set_pos(1.0 if on else 0.0)

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(42, 25)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, 42, 25).translated((self.width() - 42) / 2, (self.height() - 25) / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(theme.color(theme.FILL_STRONG), theme.color(theme.ACCENT), self._pos))
        p.drawRoundedRect(r, 12.5, 12.5)
        x = r.x() + 2 + 17 * self._pos
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, r.y() + 3, 21, 21))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 2, 21, 21))
        if self.hasFocus():
            p.setPen(QPen(theme.color(theme.ACCENT, 0.5), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 14, 14)


class LiveDot(QWidget):
    """Status dot. 'ok' breathes a soft halo; 'off' is grey; 'warn' is amber."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._state = "off"
        self._phase = 0.0

    def set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == "ok":
            animate(self, "halo", 0.0, 1.0, 2400, QEasingCurve(QEasingCurve.OutQuad), self._set_phase, loop=True)
        else:
            animate(self, "halo", 0.0, 0.0, 0, theme.SMOOTH, self._set_phase)
        self.update()

    def _set_phase(self, v):
        self._phase = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(9, 9)
        p.setPen(Qt.NoPen)
        base = {"ok": theme.ACCENT, "warn": theme.WARN}.get(self._state, theme.MUTED)
        if self._state == "ok":
            p.setBrush(theme.color(theme.ACCENT, 0.28 * (1 - self._phase)))
            p.drawEllipse(c, 4 + 5 * self._phase, 4 + 5 * self._phase)
        p.setBrush(theme.color(base))
        p.drawEllipse(c, 4, 4)


class ProgressRing(QWidget):
    """Circular progress with the 'done/total' count in the middle."""

    def __init__(self, size: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._frac = 0.0
        self._text = "0/0"

    def set_progress(self, done: int, total: int) -> None:
        self._text = f"{done}/{total}"
        animate(self, "ring", self._frac, done / total if total else 0.0, 600, theme.SMOOTH, self._set_frac)

    def _set_frac(self, v):
        self._frac = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setPen(QPen(theme.color(theme.FILL_STRONG), 6))
        p.drawEllipse(r)
        if self._frac > 0:
            p.setPen(QPen(theme.color(theme.ACCENT), 6, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, -int(self._frac * 360 * 16))
        p.setPen(theme.color(theme.TEXT))
        p.setFont(theme.font(15 if len(self._text) <= 4 else 12, QFont.Bold, display=True))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class Snackbar(QWidget):
    """Short message that rises from the bottom of its parent window, then hides itself."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFont(theme.font(13, QFont.Medium))
        self._text = ""
        self._p = 0.0
        self._hide = QTimer(self, singleShot=True, interval=2600)
        self._hide.timeout.connect(lambda: animate(self, "show", self._p, 0.0, 250, theme.SMOOTH, self._set_p,
                                                   on_done=self.hide))
        self.hide()

    def show_message(self, text: str) -> None:
        self._text = text
        fm = QFontMetrics(self.font())
        w = min(fm.horizontalAdvance(text) + 62, self.parentWidget().width() - 40)
        self.setGeometry((self.parentWidget().width() - w) // 2, self.parentWidget().height() - 72, w, 52)
        self.show()
        self.raise_()
        animate(self, "show", self._p, 1.0, 500, theme.SPRING, self._set_p)
        self._hide.start()

    def _set_p(self, v):
        self._p = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self._p)))
        p.translate(0, 24 * (1 - self._p))
        r = QRectF(0, 4, self.width(), 42)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.SNACK))
        p.drawRoundedRect(r, 12, 12)
        p.setBrush(theme.color(theme.ACCENT))
        p.drawEllipse(QPointF(24, r.center().y()), 8, 8)
        p.setPen(QPen(QColor("#ffffff"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cy = r.center().y()
        p.drawPolyline(QPolygonF([QPointF(20.5, cy), QPointF(23, cy + 2.6), QPointF(27.8, cy - 2.4)]))
        p.setPen(QColor("#ffffff"))
        p.drawText(r.adjusted(42, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, self._text)


class WarnIcon(QWidget):
    """44 px amber circle with an exclamation mark (problem dialog)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color(theme.WARN_TINT))
        p.drawEllipse(self.rect())
        p.setPen(QPen(theme.color(theme.WARN), 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(22, 13), QPointF(22, 25))
        p.drawPoint(QPointF(22, 31))


# ---------- grouped lists (macOS Settings) ----------

def group(*rows: QWidget) -> QFrame:
    """White rounded group; rows separated by hairlines inset from the left."""
    frame = QFrame()
    frame.setObjectName("group")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for i, row in enumerate(rows):
        if i:
            line = QFrame()
            line.setObjectName("sep")
            wrap = QHBoxLayout()
            wrap.setContentsMargins(14, 0, 0, 0)
            wrap.addWidget(line)
            lay.addLayout(wrap)
        lay.addWidget(row)
    return frame


def cell(*items, margins=(14, 9, 14, 9)) -> QWidget:
    """One row of a group: widgets left to right; None becomes a stretch."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(10)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return w


# ---------- list delegates ----------

ROLE_SUB = Qt.UserRole + 1
ROLE_FLAG = Qt.UserRole + 2   # flows: unsaved changes · steps: state
ROLE_TIME = Qt.UserRole + 3   # steps: when the state changed (for the pop)
ROLE_OBJ = Qt.UserRole + 4    # steps: the Step object


def monogram_color(name: str) -> QColor:
    return QColor(theme.MONOGRAMS[sum(map(ord, name)) % len(theme.MONOGRAMS)])


class FlowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 52)

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        p.setPen(Qt.NoPen)
        if selected:
            p.setBrush(theme.color(theme.ACCENT))
            p.drawRoundedRect(r, theme.R_ROW, theme.R_ROW)
        elif option.state & QStyle.State_MouseOver:
            p.setBrush(theme.color(theme.FILL))
            p.drawRoundedRect(r, theme.R_ROW, theme.R_ROW)
        name = index.data(Qt.DisplayRole) or ""
        icon = QRectF(r.x() + 8, r.center().y() - 16, 32, 32)
        p.setBrush(monogram_color(name))
        p.drawRoundedRect(icon, 9, 9)
        p.setPen(QColor("#ffffff"))
        p.setFont(theme.font(14, QFont.Bold))
        p.drawText(icon, Qt.AlignCenter, (name[:1] or "?").upper())
        fg = QColor("#ffffff") if selected else theme.color(theme.TEXT)
        text_x = icon.right() + 10
        dirty = bool(index.data(ROLE_FLAG))
        width = r.right() - text_x - (18 if dirty else 8)
        p.setPen(fg)
        p.setFont(theme.font(13, QFont.DemiBold))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(text_x, r.y() + 7, width, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideRight, int(width)))
        sub = index.data(ROLE_SUB) or ""
        sub_c = QColor(255, 255, 255, 200) if selected else theme.color(theme.MUTED)
        p.setPen(sub_c)
        p.setFont(theme.font(12))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(text_x, r.y() + 26, width, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(sub, Qt.ElideRight, int(width)))
        if dirty:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff") if selected else theme.color(theme.ACCENT))
            p.drawEllipse(QPointF(r.right() - 10, r.center().y()), 3.5, 3.5)
        p.restore()


class StepList(QListWidget):
    """Steps as a grouped list with a staggered entrance and popping state icons. Drag to reorder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("steps")
        self.setItemDelegate(StepDelegate(self))
        self.setMouseTracking(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.entrance = 0.0
        self._until = 0.0
        self._tick = QTimer(self, interval=16)
        self._tick.timeout.connect(self._frame)

    def play_entrance(self) -> None:
        self.entrance = time.monotonic() if theme.animations() else 0.0
        self.kick(0.5 + 0.04 * self.count())

    def set_state(self, row: int, state: str) -> None:
        item = self.item(row)
        if item:
            item.setData(ROLE_FLAG, state)
            item.setData(ROLE_TIME, time.monotonic() if theme.animations() else 0.0)
            self.kick(0.7)

    def kick(self, seconds: float) -> None:
        self._until = max(self._until, time.monotonic() + seconds)
        if theme.animations():
            self._tick.start()

    def _frame(self):
        self.viewport().update()
        if time.monotonic() > self._until:
            self._tick.stop()


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _spring(t: float, s: float = 1.6) -> float:
    t = max(0.0, min(1.0, t)) - 1
    return t * t * ((s + 1) * t + s) + 1


class StepDelegate(QStyledItemDelegate):
    THUMB = QSize(92, 30)

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 52)

    def paint(self, p: QPainter, option, index):
        lst: StepList = self.parent()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(option.rect)
        row = index.row()
        if lst.entrance:
            t = _ease_out((time.monotonic() - lst.entrance - row * 0.04) / 0.5)
            p.setOpacity(t)
            p.translate(0, 8 * (1 - t))
        p.setPen(Qt.NoPen)
        if option.state & QStyle.State_Selected:
            p.setBrush(theme.color(theme.ACCENT_TINT))
            p.drawRect(r)
        elif option.state & QStyle.State_MouseOver:
            p.setBrush(theme.color(theme.FILL, 0.03))
            p.drawRect(r)
        if row:
            p.fillRect(QRectF(r.x() + 48, r.y(), r.width() - 48, 1), theme.color(theme.SEP))
        cy = r.center().y()
        # number
        p.setBrush(theme.color(theme.FILL))
        p.drawEllipse(QPointF(r.x() + 25, cy), 11, 11)
        p.setPen(theme.color(theme.MUTED))
        p.setFont(theme.font(11, QFont.DemiBold))
        p.drawText(QRectF(r.x() + 14, cy - 11, 22, 22), Qt.AlignCenter, str(row + 1))
        # target thumbnail
        thumb = QRectF(r.x() + 48, cy - 15, self.THUMB.width(), self.THUMB.height())
        p.setPen(QPen(theme.color(theme.SEP), 1))
        p.setBrush(QColor("#f3f5f8"))
        p.drawRoundedRect(thumb, theme.R_THUMB, theme.R_THUMB)
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            size = pix.deviceIndependentSize()
            target = QRectF(thumb.center().x() - size.width() / 2, thumb.center().y() - size.height() / 2,
                            size.width(), size.height())
            p.drawPixmap(target, pix, QRectF(pix.rect()))
        else:
            p.setPen(theme.color(theme.MUTED))
            p.setFont(theme.font(11))
            p.drawText(thumb, Qt.AlignCenter, index.data(Qt.ToolTipRole) or "")
        # texts
        x = thumb.right() + 12
        w = r.right() - x - 46
        p.setPen(theme.color(theme.TEXT))
        p.setFont(theme.font(13, QFont.DemiBold))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(x, r.y() + 8, w, 19), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, int(w)))
        p.setPen(theme.color(theme.MUTED))
        p.setFont(theme.font(12))
        fm = QFontMetrics(p.font())
        p.drawText(QRectF(x, r.y() + 26, w, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(index.data(ROLE_SUB) or "", Qt.ElideRight, int(w)))
        # state
        since = index.data(ROLE_TIME) or 0.0
        paint_state(p, QPointF(r.right() - 26, cy), index.data(ROLE_FLAG) or "ready",
                    (time.monotonic() - since) if since else 10.0)
        p.restore()


def paint_state(p: QPainter, c: QPointF, state: str, age: float) -> None:
    """ready: grey ring · found: blue disc that pops, then a check that draws itself ·
    missing: grey disc with a dash · ambiguous: amber '!'."""
    p.save()
    if state == "ready":
        p.setPen(QPen(theme.color(theme.FILL_STRONG), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, 9, 9)
    else:
        s = _spring(age / 0.35)
        ok = state == "found"
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color({"found": theme.ACCENT, "missing": theme.FILL_STRONG}.get(state, theme.WARN)))
        p.drawEllipse(c, 10 * s, 10 * s)
        p.setPen(QPen(QColor("#ffffff"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if ok:
            k = _ease_out((age - 0.12) / 0.3)
            pts = [QPointF(c.x() - 4.2, c.y() + 0.3), QPointF(c.x() - 1.4, c.y() + 3.1), QPointF(c.x() + 4.4, c.y() - 2.9)]
            lens = [math.dist((pts[0].x(), pts[0].y()), (pts[1].x(), pts[1].y())),
                    math.dist((pts[1].x(), pts[1].y()), (pts[2].x(), pts[2].y()))]
            drawn = k * sum(lens)
            if drawn > 0:
                a = min(drawn / lens[0], 1)
                p.drawLine(pts[0], pts[0] + (pts[1] - pts[0]) * a)
                if drawn > lens[0]:
                    b = (drawn - lens[0]) / lens[1]
                    p.drawLine(pts[1], pts[1] + (pts[2] - pts[1]) * b)
        elif state == "missing":  # not on screen right now: neutral, it's normal before the previous click
            p.setPen(QPen(theme.color(theme.MUTED), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(c.x() - 4 * s, c.y()), QPointF(c.x() + 4 * s, c.y()))
        elif s > 0.6:
            p.drawLine(QPointF(c.x(), c.y() - 4.5), QPointF(c.x(), c.y() + 1))
            p.drawPoint(QPointF(c.x(), c.y() + 4.5))
    p.restore()

