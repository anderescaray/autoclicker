"""Runs a flow in a background thread with an always-on-top progress panel and F12 to stop."""

from __future__ import annotations

import datetime
import logging
import threading

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout,
    QWidget,
)

from .. import engine, storage, vision
from ..desktop import HotkeyListener, MssScreen, PynputInput, find_monitor, list_monitors
from ..model import Flow
from .common import find_on_monitors, grab_monitors, qscreen_for, show_again, visible_windows
from .dialogs import RELOCATE, ProblemDialog
from .region_picker import mark_list
from . import theme
from .widgets import PillButton, ProgressRing

log = logging.getLogger(__name__)
STOP_KEY = "f12"


class RunPanel(QWidget):
    """Floating card: first 'ready' (Start / Cancel), then a progress ring, the current step and Stop (F12)."""

    stop_clicked = Signal()
    start_clicked = Signal()

    def __init__(self, flow: Flow, max_items: int):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setWindowTitle("AutoClicker Visual — running")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.max_items = max_items
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)  # room for the shadow
        card = QFrame()
        card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(card, blurRadius=36, offset=QPointF(0, 10), color=QColor(15, 22, 40, 70))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 16, 16, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        self.ring = ProgressRing()
        self.ring.set_progress(0, max_items)
        name = QLabel(flow.name)
        name.setFont(theme.font(15, QFont.Bold, display=True))
        self.status = QLabel("Show the list on screen, then press Start.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        grid.addWidget(self.ring, 0, 0, 2, 1)
        grid.addWidget(name, 0, 1, Qt.AlignBottom)
        grid.addWidget(self.status, 1, 1, Qt.AlignTop)
        self.ready_row = QWidget()
        ready = QHBoxLayout(self.ready_row)
        ready.setContentsMargins(0, 0, 0, 0)
        cancel = PillButton("Cancel")
        cancel.clicked.connect(self.stop_clicked)
        start = PillButton("Start", "filled", play=True)
        start.clicked.connect(self.start_clicked)
        ready.addStretch(1)
        ready.addWidget(cancel)
        ready.addWidget(start)
        self.run_row = QWidget()
        row = QHBoxLayout(self.run_row)
        row.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Or push the mouse into a corner")
        hint.setObjectName("hint")
        stop = PillButton("Stop · F12", "danger")
        stop.clicked.connect(self.stop_clicked)
        row.addWidget(hint, 1)
        row.addWidget(stop)
        self.run_row.hide()
        grid.addWidget(self.ready_row, 2, 0, 1, 2)
        grid.addWidget(self.run_row, 2, 0, 1, 2)
        self.setFixedWidth(400)
        self._drag = None

    def place(self, work_monitor):
        """Top-centre, like the recording capsule: of another monitor if there is one, else of the work monitor."""
        work = qscreen_for(work_monitor)
        others = [s for s in QApplication.screens() if s is not work]
        geo = (others[0] if others else work).availableGeometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2, geo.top())

    def set_running(self):
        self.ready_row.hide()
        self.run_row.show()
        self.status.setText("Looking for the list…")

    def set_progress(self, item: int, step: int | None, total: int, label: str):
        self.ring.set_progress(item - 1, self.max_items)
        self.status.setText(f"Item {item} · <b style=\"color:{theme.ACCENT_TEXT}\">{label}</b>"
                            + (f" · step {step + 1} of {total}" if step is not None else ""))

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class RunController(QObject):
    """One run at a time. Signals bridge the worker thread to the GUI thread."""

    _progress = Signal(int, object, str)
    _problem = Signal(object, object)
    _done = Signal(object)
    _stop_key = Signal()
    finished = Signal(object)  # RunResult

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress.connect(self._on_progress, Qt.QueuedConnection)
        self._problem.connect(self._on_problem, Qt.QueuedConnection)
        self._done.connect(self._on_done, Qt.QueuedConnection)
        self._stop_key.connect(self.stop, Qt.QueuedConnection)
        self.running = False

    def start(self, flow: Flow, images: dict, max_items: int | None = None, save_result: bool = True,
              parent=None) -> bool:
        """Hide our windows and show the panel, ready. The run itself begins when the user presses Start."""
        if self.running:
            return False
        self.flow, self.images, self.save_result = flow, images, save_result
        self.max_items = max_items if max_items is not None else flow.run.max_items
        self.stop_event = threading.Event()
        self.last_problem = None
        self.runner = None
        self.running = True

        self._hidden = visible_windows()
        for w in self._hidden:
            w.hide()
        self.panel = RunPanel(flow, self.max_items)
        self.panel.stop_clicked.connect(self.stop)
        self.panel.start_clicked.connect(self._begin)
        self.panel.place(flow.monitor)
        self.panel.show()
        self.hotkey = HotkeyListener(lambda name: name == STOP_KEY and self._stop_key.emit())
        self.hotkey.start()
        return True

    def _begin(self):
        self.panel.set_running()
        QTimer.singleShot(300, self._launch)  # let the click and the panel settle before the first screenshot

    def _launch(self):
        if self.stop_event.is_set():
            return self._cancel()
        flow = self.flow
        anchor = self.images[flow.anchor_image]
        mon = find_on_monitors(anchor, flow.anchor_confidence, prefer=flow.monitor.index)
        if mon is None:  # not on screen: run on its last monitor, so the engine asks what to do
            mon = find_monitor(flow.monitor.index) or next(iter(list_monitors()), None)
            if mon is None:
                QMessageBox.warning(None, "No screen", "No monitor can be captured right now.")
                return self._cancel()
            f = flow.monitor
            if (mon.width, mon.height, mon.scale) != (f.width, f.height, f.scale):
                answer = QMessageBox.warning(
                    None, "Display settings changed",
                    f"The list was marked on a {f.width}×{f.height} screen at {round(f.scale * 100)} %, "
                    f"but it isn't visible now and monitor {mon.index} is {mon.width}×{mon.height} at "
                    f"{round(mon.scale * 100)} %.\n\nImages may not be found at a different Windows display "
                    "scale. Use the original scale, or mark the list and record the steps again.\n\nRun anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return self._cancel()
        self.monitor = mon
        flow.monitor = mon
        self.runner = engine.Runner(
            flow, self.images, MssScreen(mon), PynputInput(mon), ask=self._ask_from_worker,
            on_progress=lambda item, step, label: self._progress.emit(item, step, label),
            stop_event=self.stop_event)
        log.info("Run started: %s on monitor %d (max %d)", flow.name, mon.index, self.max_items)
        threading.Thread(target=self._work, daemon=True).start()

    def _use_monitor(self, mon) -> None:
        """The list is now on another monitor: point the (paused) runner at it."""
        log.info("Following the list to monitor %d", mon.index)
        self.monitor = self.flow.monitor = mon
        self.runner.screen = MssScreen(mon)
        self.runner.inp = PynputInput(mon)
        self.runner._size = None
        self.runner._mouse = None

    def _cancel(self):
        self.running = False
        self.hotkey.stop()
        self.panel.close()
        show_again(self._hidden)

    def stop(self):
        if not self.running:
            return
        self.stop_event.set()
        if self.runner is None:  # not started yet: just cancel
            self._cancel()
        else:
            self.panel.status.setText("Stopping…")

    # worker thread

    def _work(self):
        try:
            result = self.runner.run(self.max_items)
        except Exception as e:  # the run must always end cleanly and visibly
            log.exception("Unexpected error during run")
            result = engine.RunResult(engine.STOPPED, 0, f"Unexpected error: {e}")
        self._done.emit(result)

    def _ask_from_worker(self, problem: engine.Problem) -> str:
        holder = {"event": threading.Event(), "answer": engine.STOP}
        self._problem.emit(problem, holder)
        holder["event"].wait()
        return holder["answer"]

    # GUI thread

    def _on_progress(self, item, step, label):
        self.panel.set_progress(item, step, len(self.flow.steps), label)

    def _on_problem(self, problem: engine.Problem, holder):
        self.last_problem = problem
        try:
            dialog = ProblemDialog(problem)
            dialog.exec()
            answer = dialog.answer
            if answer == RELOCATE:
                answer = engine.RETRY if self._relocate(problem) else engine.STOP
            elif answer == engine.RETRY and problem.kind == engine.ANCHOR_MISSING:
                mon = find_on_monitors(self.runner.anchor_img, self.flow.anchor_confidence, self.monitor.index)
                if mon is not None and mon.index != self.monitor.index:
                    self._use_monitor(mon)
            if answer == engine.RETRY:
                self.runner._mouse = None  # the user just used the mouse; don't treat that as a takeover
                self.last_problem = None
            holder["answer"] = answer
        finally:
            holder["event"].set()

    def _relocate(self, problem: engine.Problem) -> bool:
        frames = grab_monitors()
        if problem.screen is not None:  # show what the run saw on its monitor
            frames = [(m, problem.screen if m.index == self.monitor.index else f) for m, f in frames]
        marked = mark_list(frames)
        if not marked:
            return False
        mon, anchor, offset, row = marked
        if mon.index != self.monitor.index:
            self._use_monitor(mon)
        flow = self.flow
        flow.anchor_image = storage.add_flow_image(flow, anchor, "anchor")
        flow.first_row.offset = offset
        flow.first_row.filled_score = vision.row_score(row)
        self.images[flow.anchor_image] = anchor
        self.runner.anchor_img = anchor
        if self.save_result and QMessageBox.question(
                None, "Update flow", "Save this new position of the list in the flow?") == QMessageBox.Yes:
            storage.save_flow(flow)
        return True

    def _on_done(self, result: engine.RunResult):
        self.running = False
        self.hotkey.stop()
        self.panel.close()
        show_again(self._hidden)
        if self.last_problem is not None and self.last_problem.screen is not None:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = storage.logs_dir() / f"stop-{stamp}.png"
            storage.write_image(path, self.last_problem.screen)
            log.info("Screen at stop saved to %s", path)
        if self.save_result:
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            self.flow.last_run = f"{stamp} · {result.items} item(s) · {result.status}"
            storage.save_flow(self.flow)
        self.finished.emit(result)  # finished and limit are shown as a snackbar by the main window
        if result.status == engine.STOPPED:
            box = QMessageBox(QMessageBox.Warning, "Stopped", f"{result.message}\n\nItems processed: {result.items}")
            box.setWindowFlag(Qt.WindowStaysOnTopHint)
            box.exec()
