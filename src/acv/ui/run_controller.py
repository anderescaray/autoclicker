"""Runs a flow in a background thread with an always-on-top progress panel and F12 to stop."""

from __future__ import annotations

import datetime
import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from .. import engine, storage, vision
from ..desktop import HotkeyListener, MssScreen, PynputInput, find_monitor
from ..model import Flow
from .common import qscreen_for
from .dialogs import RELOCATE, ProblemDialog
from .region_picker import mark_list

log = logging.getLogger(__name__)
STOP_KEY = "f12"


class RunPanel(QWidget):
    stop_clicked = Signal()

    def __init__(self, flow: Flow, max_items: int):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("AutoClicker Visual — running")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        name = QLabel(flow.name)
        name.setObjectName("title")
        self.status = QLabel("Starting…")
        self.bar = QProgressBar()
        self.bar.setRange(0, max_items)
        self.bar.setFormat("%v / %m")
        stop = QPushButton("Stop (F12)")
        stop.setObjectName("danger")
        stop.clicked.connect(self.stop_clicked)
        lay.addWidget(name)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(self.bar, 1)
        row.addWidget(stop)
        lay.addLayout(row)
        self.setFixedWidth(380)

    def place(self, work_monitor):
        """Bottom-right of another monitor if there is one, so it never covers the work area."""
        work = qscreen_for(work_monitor)
        others = [s for s in QApplication.screens() if s is not work]
        geo = (others[0] if others else work).availableGeometry()
        self.adjustSize()
        self.move(geo.right() - self.width() - 24, geo.bottom() - self.height() - 48)

    def set_progress(self, item: int, step: int | None, total: int, label: str):
        self.bar.setValue(item - 1)
        self.status.setText(f"Item {item}  ·  step {step + 1}/{total}  ·  {label}" if step is not None
                            else f"Item {item}")


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
        if self.running:
            return False
        mon = find_monitor(flow.monitor.index)
        if mon is None:
            QMessageBox.warning(parent, "Monitor not found",
                                f"Monitor {flow.monitor.index} is not connected. Choose another one in the editor.")
            return False
        f = flow.monitor
        if (mon.width, mon.height, mon.scale) != (f.width, f.height, f.scale):
            answer = QMessageBox.warning(
                parent, "Display settings changed",
                f"Monitor {mon.index} is now {mon.width}×{mon.height} at {round(mon.scale * 100)} %, "
                f"but the flow was recorded at {f.width}×{f.height} at {round(f.scale * 100)} %.\n\n"
                "Images may not be found. Restore the original Windows display scale, or record the flow again.\n\n"
                "Run anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return False
        self.flow, self.images, self.monitor, self.save_result = flow, images, mon, save_result
        self.max_items = max_items if max_items is not None else flow.run.max_items
        self.stop_event = threading.Event()
        self.last_problem = None
        self.running = True

        self._hidden = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
        for w in self._hidden:
            w.hide()
        self.panel = RunPanel(flow, self.max_items)
        self.panel.stop_clicked.connect(self.stop)
        self.panel.place(mon)
        self.panel.show()
        self.hotkey = HotkeyListener(lambda name: name == STOP_KEY and self._stop_key.emit())
        self.hotkey.start()

        self.runner = engine.Runner(
            flow, images, MssScreen(mon), PynputInput(mon), ask=self._ask_from_worker,
            on_progress=lambda item, step, label: self._progress.emit(item, step, label),
            stop_event=self.stop_event)
        log.info("Run started: %s (max %d)", flow.name, self.max_items)
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def stop(self):
        if self.running:
            self.stop_event.set()
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
            if answer == engine.RETRY:
                self.runner._mouse = None  # the user just used the mouse; don't treat that as a takeover
                self.last_problem = None
            holder["answer"] = answer
        finally:
            holder["event"].set()

    def _relocate(self, problem: engine.Problem) -> bool:
        frame = problem.screen if problem.screen is not None else MssScreen(self.monitor).grab()
        marked = mark_list(frame, self.monitor)
        if not marked:
            return False
        anchor, offset, row = marked
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
        for w in self._hidden:
            w.show()
        if self.last_problem is not None and self.last_problem.screen is not None:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = storage.logs_dir() / f"stop-{stamp}.png"
            storage.write_image(path, self.last_problem.screen)
            log.info("Screen at stop saved to %s", path)
        if self.save_result:
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            self.flow.last_run = f"{stamp} · {result.items} item(s) · {result.status}"
            storage.save_flow(self.flow)
        icon = QMessageBox.Information if result.status == engine.FINISHED else QMessageBox.Warning
        title = {engine.FINISHED: "Done", engine.LIMIT: "Limit reached"}.get(result.status, "Stopped")
        box = QMessageBox(icon, title, f"{result.message}\n\nItems processed: {result.items}")
        box.setWindowFlag(Qt.WindowStaysOnTopHint)
        box.exec()
        self.finished.emit(result)
