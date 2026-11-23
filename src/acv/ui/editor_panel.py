"""The flow editor shown on the right of the main window (docs/design/ui-spec.md §1)."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QDoubleSpinBox, QVBoxLayout, QWidget,
)

from .. import storage, vision
from ..desktop import IS_WINDOWS, MssScreen, list_monitors, root_window_at
from ..engine import probe_step
from ..model import (
    CLICK_IMAGE, CLICK_POINT, IMAGE_STEPS, KEY, STEP_TYPE_NAMES, STEP_TYPES, TEXT, WAIT, WAIT_IMAGE, Flow, Point,
    Step,
)
from ..recorder import Recorder
from .common import HighlightOverlay, close_overlays, fit_pixmap, grab_monitors, hidden_windows, show_again, visible_windows, wait_ms
from .dialogs import StepDialog
from .recording_bar import RecordingBar
from .region_picker import mark_list, pick_regions
from .widgets import (
    ROLE_FLAG, ROLE_OBJ, ROLE_SUB, LiveDot, PillButton, StepList, Switch, cell, group,
)

log = logging.getLogger(__name__)


class LiveChecker(QThread):
    """About twice a second: is the anchor on any monitor, and does the first row have an item?"""

    status = Signal(object, object, object)  # anchor found (bool | None), row filled (bool | None), MonitorInfo | None

    def __init__(self, editor: EditorPanel):
        super().__init__()
        self.editor = editor
        self.last_row = None

    def run(self):
        screens: dict = {}
        monitors, listed_at = [], 0.0
        while not self.isInterruptionRequested():
            try:
                cfg = self.editor.live_config()
                if cfg is None:
                    self.status.emit(None, None, None)
                else:
                    if time.monotonic() - listed_at > 5:  # monitors can be plugged in or out
                        monitors, listed_at = safe_monitors(), time.monotonic()
                    prefer, anchor, offset, filled_score, empty, confidence = cfg
                    ordered = sorted(monitors, key=lambda m: m.index != prefer)  # last known monitor first
                    found_on, filled = None, None
                    for mon in ordered:
                        key = (mon.left, mon.top, mon.width, mon.height)
                        screen = screens.get(key) or screens.setdefault(key, MssScreen(mon))
                        frame = screen.grab()
                        status, a = vision.locate(frame, anchor, confidence)
                        if status == vision.FOUND:
                            found_on = mon
                            row = vision.crop(frame, vision.row_rect(a, offset))
                            if row is not None:
                                self.last_row = row
                                filled = vision.is_row_filled(row, filled_score, empty)
                            break
                    self.status.emit(found_on is not None, filled, found_on)
            except Exception:
                log.exception("Live check failed")
            self.msleep(500)


def safe_monitors():
    """Connected monitors; empty (and logged) if the system can't report them right now."""
    try:
        return list_monitors()
    except Exception:
        log.exception("Cannot list monitors")
        return []


def caption(text: str, extra: str = "") -> QLabel:
    label = QLabel(text + (f'<span style="font-weight:400"> · {extra}</span>' if extra else ""))
    label.setObjectName("caption")
    return label


def label(text: str = "", name: str = "") -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


def link(text: str, slot, quiet: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("variant", "quietLink" if quiet else "link")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class EditorPanel(QWidget):
    saved = Signal()               # the flow was written to disk
    changed = Signal()             # anything in the flow changed (name, steps…)
    notify = Signal(str)           # short message for the snackbar

    def __init__(self, run_controller, parent=None):
        super().__init__(parent)
        self.setObjectName("editor")
        self.setAttribute(Qt.WA_StyledBackground)
        self.run_controller = run_controller
        self.flow: Flow | None = None
        self.images: dict = {}
        self._saved_state = None
        self._dirty = False
        self.recorder = None
        self._build()
        self.checker = LiveChecker(self)
        self.checker.status.connect(self._on_live_status)
        self.checker.start()
        self._dirty_timer = QTimer(self, interval=400)
        self._dirty_timer.timeout.connect(self._check_dirty)
        self._dirty_timer.start()

    # ---------- layout ----------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(16)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title = label("", "title")
        self.title.setToolTip("Double-click to rename")
        self.title.installEventFilter(self)
        self.subtitle = label("", "subtitle")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.sim_btn = PillButton("Simulate")
        self.sim_btn.setToolTip("Find each step on screen and highlight it. Nothing is clicked.")
        self.sim_btn.clicked.connect(self.simulate)
        self.one_btn = PillButton("Run 1 item", "tonal")
        self.one_btn.setToolTip("Process only the first item of the list, for real.")
        self.one_btn.clicked.connect(self.run_one)
        self.run_btn = PillButton("Run", "filled", play=True, large=True)
        self.run_btn.setToolTip("Process every item until the list is empty. F12 stops.")
        self.run_btn.clicked.connect(self.run_all)
        for b in (self.sim_btn, self.one_btn, self.run_btn):
            head.addWidget(b, 0, Qt.AlignVCenter)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(18)
        root.addLayout(body, 1)

        # left column: screen, list, options
        left = QWidget()
        left.setObjectName("editorInner")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(0, 0, 6, 0)
        lcol.setSpacing(8)
        self.monitor_name = label("")
        self.monitor_size = label("", "mono")
        screen_hint = label("Found automatically on any screen, even if you move the window.", "hint")
        screen_hint.setWordWrap(True)
        lcol.addWidget(caption("Screen"))
        lcol.addWidget(group(cell(label("Monitor", "muted"), None, self.monitor_name),
                             cell(label("Size", "muted"), None, self.monitor_size), cell(screen_hint)))
        lcol.addSpacing(6)

        self.anchor_thumb = label("Not marked yet", "muted")
        self.row_thumb = label("Not marked yet", "muted")
        self.live_dot = LiveDot()
        self.live_text = label("Mark the list to start checking")
        self.live_note = label("", "hint")
        lcol.addWidget(caption("The list"))
        lcol.addWidget(group(
            cell(self._fixed(label("Anchor", "muted")), self.anchor_thumb, None),
            cell(self._fixed(label("First row", "muted")), self.row_thumb, None),
            cell(self.live_dot, self.live_text, None, self.live_note),
            cell(link("Mark anchor and first row", self.mark_list), None, label("›", "muted")),
            cell(link("Save current state as empty", self.save_empty_sample, quiet=True), None),
        ))
        lcol.addSpacing(6)

        self.pause_sw, self.max_sw = Switch(), Switch()
        self.pause_sw.toggled.connect(lambda v: self.flow and setattr(self.flow.run, "pause_on_user_mouse", v))
        self.max_sw.toggled.connect(lambda v: self.flow and setattr(self.flow.run, "maximize_window", v))
        self.max_items = QSpinBox()
        self.max_items.setRange(1, 100000)
        self.max_items.setFixedWidth(96)
        self.max_items.setButtonSymbols(QSpinBox.NoButtons)
        self.max_items.setAlignment(Qt.AlignRight)
        self.max_items.valueChanged.connect(lambda v: self.flow and setattr(self.flow.run, "max_items", v))
        self.wait_change = QDoubleSpinBox()
        self.wait_change.setRange(1, 600)
        self.wait_change.setSuffix(" s")
        self.wait_change.setDecimals(0)
        self.wait_change.setFixedWidth(96)
        self.wait_change.setButtonSymbols(QSpinBox.NoButtons)
        self.wait_change.setAlignment(Qt.AlignRight)
        self.wait_change.valueChanged.connect(lambda v: self.flow and setattr(self.flow.run, "wait_list_change_s", v))
        lcol.addWidget(caption("Options"))
        lcol.addWidget(group(
            cell(label("Pause if I move the mouse"), None, self.pause_sw),
            cell(label("Maximise the window first"), None, self.max_sw),
            cell(label("Max items per run"), None, self.max_items),
            cell(label("Wait for the list to update"), None, self.wait_change),
        ))
        lcol.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("editorScroll")
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(330)
        body.addWidget(scroll)

        # right column: steps
        right = QVBoxLayout()
        right.setSpacing(8)
        bar = QHBoxLayout()
        bar.addWidget(caption("Steps", "repeated for each item"))
        bar.addStretch(1)
        self.record_btn = PillButton("Record", dot=True)
        self.record_btn.setToolTip("Do the clicks for one item; each one becomes a step.")
        self.record_btn.clicked.connect(self.start_recording)
        add = PillButton("Add step")
        menu = QMenu(add)
        for t in STEP_TYPES:
            menu.addAction(STEP_TYPE_NAMES[t], lambda t=t: self.add_step(t))
        add.setMenu(menu)
        bar.addWidget(self.record_btn)
        bar.addWidget(add)
        right.addLayout(bar)
        self.steps = StepList()
        self.steps.setToolTip("Drag a step to reorder. Double-click to edit. Right-click for more.")
        self.steps.itemDoubleClicked.connect(lambda _: self.edit_step())
        self.steps.model().rowsMoved.connect(self._on_rows_moved)
        self.steps.setContextMenuPolicy(Qt.CustomContextMenu)
        self.steps.customContextMenuRequested.connect(self._step_menu)
        right.addWidget(self.steps, 1)
        self.steps_empty = label("No steps yet. Press Record and do the clicks for one item.", "muted")
        self.steps_empty.setAlignment(Qt.AlignCenter)
        right.addWidget(self.steps_empty, 1)
        foot = QHBoxLayout()
        for text, slot in (("Test step", self.test_step), ("Edit", self.edit_step)):
            b = PillButton(text)
            b.clicked.connect(slot)
            foot.addWidget(b)
        foot.addStretch(1)
        delete = PillButton("Delete")
        delete.clicked.connect(self.delete_step)
        self.save_btn = PillButton("Save", "tonal")
        self.save_btn.clicked.connect(self.save)
        foot.addWidget(delete)
        foot.addWidget(self.save_btn)
        right.addLayout(foot)
        body.addLayout(right, 1)

    @staticmethod
    def _fixed(w: QWidget, width: int = 70) -> QWidget:
        w.setFixedWidth(width)
        return w

    def eventFilter(self, obj, e):
        if obj is self.title and e.type() == QEvent.MouseButtonDblClick:
            self.rename()
            return True
        return super().eventFilter(obj, e)

    # ---------- loading & state ----------

    def load(self, flow: Flow) -> None:
        self.flow = flow
        self.images = {}
        self._saved_state = flow.to_dict()
        for w, v in ((self.pause_sw, flow.run.pause_on_user_mouse), (self.max_sw, flow.run.maximize_window),
                     (self.max_items, flow.run.max_items), (self.wait_change, flow.run.wait_list_change_s)):
            w.blockSignals(True)
            w.setChecked(v) if isinstance(w, Switch) else w.setValue(v)
            w.blockSignals(False)
        self.checker.last_row = None
        self._refresh_all()
        self.steps.play_entrance()
        self._check_dirty()

    def is_dirty(self) -> bool:
        return self.flow is not None and self.flow.to_dict() != self._saved_state

    def _check_dirty(self):
        if self.flow is None:
            return
        data = self.flow.to_dict()
        if data != getattr(self, "_last_seen", None):
            self._last_seen = data
            self.changed.emit()
        dirty = data != self._saved_state
        self.save_btn.setEnabled(dirty)
        self._refresh_header()
        self._dirty = dirty

    def maybe_save(self) -> bool:
        """Before leaving this flow: True to continue, False to stay."""
        if not self.is_dirty():
            return True
        answer = QMessageBox.question(self, "Unsaved changes", f"Save the changes to “{self.flow.name}”?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save()
        self.load(storage.load_flow(self.flow.id))  # discard
        return True

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
        if f is None:
            return None
        anchor = self.images.get(f.anchor_image)
        if anchor is None or not f.first_row.offset.w:
            return None
        return (f.monitor.index, anchor, f.first_row.offset, f.first_row.filled_score,
                self.images.get(f.first_row.empty_sample), f.anchor_confidence)

    def selected(self) -> int:
        return self.steps.currentRow()

    def need(self, monitor=True, anchor=False, steps=False) -> bool:
        f = self.flow
        missing = None
        if monitor and not f.monitor.width:
            missing = "Choose the monitor where the list is shown first."
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

    def _refresh_header(self):
        f = self.flow
        self.title.setText(f.name)
        n = len(f.steps)
        self.subtitle.setText(f"{n} step{'s' if n != 1 else ''} · up to {f.run.max_items} items per run")

    def _refresh_all(self):
        self._refresh_header()
        self._show_monitor()
        self._set_thumb(self.anchor_thumb, self.image(self.flow.anchor_image))
        if self.checker.last_row is None:
            self._set_thumb(self.row_thumb, None)
        self._refresh_steps()

    @staticmethod
    def _set_thumb(lbl: QLabel, img) -> None:
        if img is None:
            lbl.setObjectName("muted")
            lbl.setPixmap(QPixmap())
            lbl.setText("Not marked yet")
        else:
            lbl.setObjectName("thumb")
            lbl.setPixmap(fit_pixmap(img, 190, 26))
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

    def _refresh_steps(self, select: int | None = None):
        self.steps.clear()
        for s in self.flow.steps:
            item = QListWidgetItem(s.label or STEP_TYPE_NAMES.get(s.type, s.type))
            item.setData(ROLE_SUB, self._step_sub(s))
            item.setData(ROLE_OBJ, s)
            item.setData(ROLE_FLAG, "ready")
            img = self.image(s.image) if s.type in IMAGE_STEPS else None
            if img is not None:
                item.setData(Qt.DecorationRole, fit_pixmap(img, 86, 26))
            else:
                item.setData(Qt.ToolTipRole, {CLICK_POINT: "⌖ row", KEY: "⌨ key", TEXT: "Aa text", WAIT: "⏱ wait"}
                             .get(s.type, ""))
            self.steps.addItem(item)
        has = bool(self.flow.steps)
        self.steps.setVisible(has)
        self.steps_empty.setVisible(not has)
        if select is not None and 0 <= select < self.steps.count():
            self.steps.setCurrentRow(select)

    @staticmethod
    def _step_sub(s: Step) -> str:
        click = {(1, "left"): "Click", (2, "left"): "Double-click"}.get((s.clicks, s.button), "Right-click")
        if s.type == CLICK_IMAGE:
            return f"{click} · waits up to {s.timeout_s:g} s"
        if s.type == CLICK_POINT:
            return f"{click} · fixed spot from the anchor ({s.point.x}, {s.point.y})"
        if s.type == WAIT_IMAGE:
            return f"Wait until it appears · up to {s.timeout_s:g} s"
        return s.describe()

    def _on_rows_moved(self, *_):
        self.flow.steps = [self.steps.item(i).data(ROLE_OBJ) for i in range(self.steps.count())]
        self.steps.viewport().update()

    def _on_live_status(self, anchor, filled, monitor):
        if monitor is not None and self.flow is not None and (monitor.index, monitor.left, monitor.top) != (
                self.flow.monitor.index, self.flow.monitor.left, self.flow.monitor.top):
            self.flow.monitor = monitor  # the list moved to another screen: follow it
            self._show_monitor()
        if anchor is None:
            self.live_dot.set_state("off")
            self.live_text.setText("Mark the list to start checking")
            self.live_note.setText("")
            return
        self.live_note.setText(f"live · monitor {monitor.index}" if monitor else "live")
        if not anchor:
            self.live_dot.set_state("warn")
            self.live_text.setText("Not on any screen right now")
            return
        self.live_dot.set_state("ok")
        self.live_text.setText("Found, with an item" if filled else "Found · the list is empty")
        if self.checker.last_row is not None:
            self._set_thumb(self.row_thumb, self.checker.last_row)

    # ---------- flow ----------

    def rename(self):
        name, ok = QInputDialog.getText(self, "Rename flow", "Name:", text=self.flow.name)
        if ok and name.strip():
            self.flow.name = name.strip()
            self._check_dirty()

    def _show_monitor(self):
        m = self.flow.monitor
        if not self.flow.anchor_image or not m.width:
            self.monitor_name.setText("Set when you mark the list")
            self.monitor_size.setText("—")
            return
        self.monitor_name.setText(f"Monitor {m.index}")
        self.monitor_size.setText(f"{m.width} × {m.height} · {round(m.scale * 100)} %")

    def mark_list(self):
        with hidden_windows():
            frames = grab_monitors()
        if not frames:
            QMessageBox.warning(self, "No screen", "The screens can't be captured right now. Try again.")
            return
        marked = mark_list(frames, self)
        self.window().activateWindow()
        if not marked:
            return
        monitor, anchor, offset, row = marked
        f = self.flow
        f.monitor = monitor
        f.anchor_image = self.add_image(anchor, "anchor")
        f.first_row.offset = offset
        f.first_row.filled_score = vision.row_score(row)
        f.first_row.empty_sample = None
        self.checker.last_row = row
        self._set_thumb(self.row_thumb, row)
        self._refresh_all()
        self.notify.emit("List marked · watch the live check")

    def save_empty_sample(self):
        row = self.checker.last_row
        if row is None:
            QMessageBox.information(self, "Not visible", "The list must be visible to save its empty state.")
            return
        if QMessageBox.question(self, "Save empty state",
                                "Is the list empty right now? The current first row will be treated as "
                                "'no more items'.") == QMessageBox.Yes:
            self.flow.first_row.empty_sample = self.add_image(row, "empty")
            self.notify.emit("Empty state saved")

    # ---------- recording ----------

    def start_recording(self):
        if not self.need(anchor=True):
            return
        self.bar = RecordingBar()
        self.bar.undo.connect(self.undo_recorded)
        self.bar.finish.connect(self.stop_recording)
        self._hidden = visible_windows()
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
        show_again(self._hidden)
        self.window().activateWindow()
        self._refresh_steps(len(self.flow.steps) - 1)
        self.steps.play_entrance()
        self.notify.emit("Recording finished · try Simulate or Run 1 item")

    # ---------- steps ----------

    def _step_menu(self, pos):
        row = self.steps.indexAt(pos).row()
        if row < 0:
            return
        self.steps.setCurrentRow(row)
        menu = QMenu(self)
        menu.addAction("Edit…", self.edit_step)
        menu.addAction("Test step", self.test_step)
        menu.addSeparator()
        menu.addAction("Move up", lambda: self.move_step(-1)).setEnabled(row > 0)
        menu.addAction("Move down", lambda: self.move_step(1)).setEnabled(row < self.steps.count() - 1)
        menu.addSeparator()
        menu.addAction("Delete", self.delete_step)
        menu.exec(self.steps.viewport().mapToGlobal(pos))

    def add_step(self, kind: str):
        step = Step(type=kind)
        if kind in (CLICK_IMAGE, WAIT_IMAGE, CLICK_POINT):
            if not self.need(anchor=kind == CLICK_POINT):
                return
            frame = self.capture()
            prompt = ("Drag around the spot to click (it will click the centre)." if kind != WAIT_IMAGE
                      else "Drag around what must appear before continuing.")
            rects = pick_regions(frame, self.flow.monitor, [prompt])
            self.window().activateWindow()
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

    def _probe(self, i: int, frame) -> str | None:
        """Highlight step i on `frame` and show the result on its row. Returns the vision status."""
        step = self.flow.steps[i]
        if step.type not in (CLICK_IMAGE, WAIT_IMAGE, CLICK_POINT):
            return None
        status, rect = probe_step(self.flow, self.all_images(), frame, step)
        text = {vision.FOUND: f"Step {i + 1} · found here",
                vision.MISSING: f"Step {i + 1} · not on screen right now",
                vision.AMBIGUOUS: f"Step {i + 1} · found in more than one place"}[status]
        HighlightOverlay(self.flow.monitor, (frame.shape[1], frame.shape[0]), rect, text, ok=status == vision.FOUND)
        self.steps.set_state(i, {vision.FOUND: "found", vision.MISSING: "missing"}.get(status, "ambiguous"))
        return status

    def test_step(self):
        i = self.selected()
        if i < 0:
            QMessageBox.information(self, "Test step", "Select a step first.")
            return
        if not self.need():
            return
        status = self._probe(i, self.capture())
        self.notify.emit({vision.FOUND: f"Step {i + 1} is on screen", vision.MISSING: f"Step {i + 1} isn't on screen now",
                          vision.AMBIGUOUS: f"Step {i + 1} appears in more than one place",
                          None: f"Step {i + 1} has nothing to find"}[status])

    def simulate(self):
        if not self.need(anchor=True, steps=True):
            return
        found = 0
        with hidden_windows():
            for i in range(len(self.flow.steps)):
                close_overlays()
                wait_ms(60)  # let the overlay disappear before the next screenshot
                frame = MssScreen(self.flow.monitor).grab()
                found += self._probe(i, frame) == vision.FOUND
                wait_ms(1300)
            close_overlays()
        self.notify.emit(f"{found} of {len(self.flow.steps)} steps on screen now · "
                         "the rest appear after each click")

    def _ready_to_run(self) -> bool:
        return self.need(anchor=True, steps=True)

    def run_one(self):
        if self._ready_to_run():
            self.run_controller.start(self.flow, self.all_images(), max_items=1, save_result=False, parent=self)

    def run_all(self):
        if not self._ready_to_run():
            return
        if self.is_dirty() and not self.save():
            return
        try:
            images = self.all_images()
            if any(v is None for v in images.values()):
                raise ValueError("missing image")
        except (OSError, ValueError):
            QMessageBox.warning(self, "Flow damaged", "Some images of this flow are missing. Record it again.")
            return
        self.run_controller.start(self.flow, images, parent=self)

    # ---------- save ----------

    def save(self) -> bool:
        if not self.flow.name:
            QMessageBox.warning(self, "Name missing", "Give the flow a name.")
            return False
        storage.save_flow(self.flow)
        self._saved_state = self.flow.to_dict()
        self._check_dirty()
        self.saved.emit()
        self.notify.emit("Saved")
        return True

    def after_run(self):
        """The run saved `last_run` into the flow file: keep the clean state in sync."""
        if self.flow is not None and not self._dirty:
            self._saved_state = self.flow.to_dict()

    def shutdown(self):
        self.checker.requestInterruption()
        self.checker.wait(2000)
