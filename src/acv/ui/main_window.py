"""Main window: flows in the sidebar, the editor on the right (docs/design/ui-spec.md §1)."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, engine, storage
from ..model import Flow
from .editor_panel import EditorPanel, safe_monitors
from .run_controller import RunController
from .tutorial import Tutorial
from .widgets import ROLE_FLAG, ROLE_SUB, FlowDelegate, PillButton, RoundButton, Snackbar

log = logging.getLogger(__name__)


def _when(flow: Flow, today: datetime.date | None = None) -> str:
    """'6 steps · ran today, 09:42' / 'ran yesterday' / 'ran 23 Nov' / 'not run yet'."""
    n = len(flow.steps)
    steps = f"{n} step{'s' if n != 1 else ''}"
    if not flow.last_run:
        return f"{steps} · not run yet"
    try:
        when = datetime.datetime.strptime(flow.last_run.split(" · ")[0], "%Y-%m-%d %H:%M")
    except ValueError:
        return f"{steps} · ran before"
    today = today or datetime.date.today()
    if when.date() == today:
        return f"{steps} · ran today, {when:%H:%M}"
    if (today - when.date()).days == 1:
        return f"{steps} · ran yesterday"
    return f"{steps} · ran {when.day} {when:%b}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 740)
        self.setMinimumSize(1060, 640)
        self.run_controller = RunController(self)
        self.run_controller.finished.connect(self._run_finished)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.empty = self._build_empty()
        self.editor = EditorPanel(self.run_controller)
        self.editor.saved.connect(lambda: self.refresh(self.editor.flow.id))
        self.editor.changed.connect(lambda: self._mark_dirty(self.editor.is_dirty()))
        self.editor.notify.connect(lambda text: self.snackbar.show_message(text))
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.editor)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.snackbar = Snackbar(central)

        QShortcut(QKeySequence.Save, self, activated=lambda: self.editor.flow and self.editor.save())
        QShortcut(QKeySequence.New, self, activated=self.new_flow)
        self.refresh()

    # ---------- layout ----------

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setAttribute(Qt.WA_StyledBackground)
        side.setFixedWidth(248)
        col = QVBoxLayout(side)
        col.setContentsMargins(10, 14, 10, 12)
        col.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(8, 0, 2, 0)
        title = QLabel("Flows")
        title.setObjectName("sideTitle")
        top.addWidget(title)
        top.addStretch(1)
        add = RoundButton("+", "New flow or import")
        menu = QMenu(add)
        menu.addAction("New flow…", self.new_flow)
        menu.addAction("Import…", self.import_flow)
        add.setMenu(menu)
        top.addWidget(add)
        col.addLayout(top)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        col.addWidget(self.search)
        self.flows = QListWidget()
        self.flows.setItemDelegate(FlowDelegate(self.flows))
        self.flows.setMouseTracking(True)
        self.flows.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.flows.currentItemChanged.connect(self._select)
        self.flows.setContextMenuPolicy(Qt.CustomContextMenu)
        self.flows.customContextMenuRequested.connect(self._flow_menu)
        col.addWidget(self.flows, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(8, 0, 2, 0)
        hint = QLabel("<b>F12</b> stops any run")
        hint.setObjectName("hint")
        foot.addWidget(hint, 1)
        helpb = RoundButton("?", "Help")
        hm = QMenu(helpb)
        hm.addAction("Tutorial", self.show_tutorial)
        hm.addAction("Open logs folder", self.open_logs)
        hm.addSeparator()
        hm.addAction(f"About {APP_NAME}", self.about)
        helpb.setMenu(hm)
        foot.addWidget(helpb)
        col.addLayout(foot)
        return side

    def _build_empty(self) -> QWidget:
        w = QWidget()
        w.setObjectName("emptyState")
        w.setAttribute(Qt.WA_StyledBackground)
        col = QVBoxLayout(w)
        col.addStretch(1)
        icon = QLabel()
        icon.setPixmap(QApplication.windowIcon().pixmap(72, 72) if not QApplication.windowIcon().isNull()
                       else QIcon().pixmap(1, 1))
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("No flows yet")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        text = QLabel("A flow repeats the clicks you do for one item of a list,\nfor every item, until the list is empty.")
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignCenter)
        btn = PillButton("New flow", "filled", large=True)
        btn.clicked.connect(self.new_flow)
        for x in (icon, title, text):
            col.addWidget(x)
        col.addSpacing(10)
        col.addWidget(btn, 0, Qt.AlignHCenter)
        col.addStretch(1)
        return w

    # ---------- list ----------

    def refresh(self, select_id: str | None = None):
        current = select_id or self.current_id()
        self.flows.blockSignals(True)
        self.flows.clear()
        for flow in storage.list_flows():
            if self.editor.flow is not None and flow.id == self.editor.flow.id:
                flow = self.editor.flow  # show live edits (name, steps)
            item = QListWidgetItem(flow.name)
            item.setData(Qt.UserRole, flow.id)
            item.setData(ROLE_SUB, _when(flow))
            item.setData(ROLE_FLAG, self.editor.flow is flow and self.editor.is_dirty())
            self.flows.addItem(item)
            if flow.id == current:
                self.flows.setCurrentItem(item)
        if self.flows.currentItem() is None and self.flows.count():
            self.flows.setCurrentRow(0)
        self.flows.blockSignals(False)
        self._filter(self.search.text())
        self._show_current()

    def current_id(self) -> str | None:
        item = self.flows.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.flows.count()):
            item = self.flows.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _show_current(self):
        flow_id = self.current_id()
        if flow_id is None:
            self.editor.flow = None
            self.stack.setCurrentWidget(self.empty)
            return
        self.stack.setCurrentWidget(self.editor)
        if self.editor.flow is None or self.editor.flow.id != flow_id:
            try:
                self.editor.load(storage.load_flow(flow_id))
            except Exception:
                log.exception("Cannot load flow")
                QMessageBox.warning(self, "Cannot open flow", "This flow could not be read. See the log for details.")

    def _select(self, item, previous):
        if item is None:
            return
        if self.editor.flow is not None and item.data(Qt.UserRole) != self.editor.flow.id:
            if not self.editor.maybe_save():
                self.flows.blockSignals(True)
                self.flows.setCurrentItem(previous)
                self.flows.blockSignals(False)
                return
            self.refresh(item.data(Qt.UserRole))
            return
        self._show_current()

    def _mark_dirty(self, dirty: bool):
        for i in range(self.flows.count()):
            item = self.flows.item(i)
            if self.editor.flow and item.data(Qt.UserRole) == self.editor.flow.id:
                item.setData(ROLE_FLAG, dirty)
                item.setText(self.editor.flow.name)
                item.setData(ROLE_SUB, _when(self.editor.flow))

    def _flow_menu(self, pos):
        item = self.flows.itemAt(pos)
        if not item:
            return
        self.flows.setCurrentItem(item)
        if self.current_id() != item.data(Qt.UserRole):
            return  # the user cancelled leaving unsaved changes
        menu = QMenu(self)
        menu.addAction("Rename…", self.editor.rename)
        menu.addAction("Duplicate…", self.duplicate_flow)
        menu.addAction("Export…", self.export_flow)
        menu.addSeparator()
        menu.addAction("Delete…", self.delete_flow)
        menu.exec(self.flows.viewport().mapToGlobal(pos))

    # ---------- actions ----------

    def new_flow(self):
        if self.editor.flow is not None and not self.editor.maybe_save():
            return
        name, ok = QInputDialog.getText(self, "New flow", "Name of the flow (e.g. 'Approve requests'):")
        if not ok or not name.strip():
            return
        flow = Flow(name=name.strip())
        monitors = safe_monitors()
        if monitors:
            flow.monitor = monitors[0]
        storage.save_flow(flow)
        self.refresh(flow.id)
        self.snackbar.show_message("Flow created · now mark the list")

    def duplicate_flow(self):
        flow = self.editor.flow
        if not flow or not self.editor.maybe_save():
            return
        name, ok = QInputDialog.getText(self, "Duplicate", "Name of the copy:", text=f"{flow.name} (copy)")
        if ok and name.strip():
            self.refresh(storage.duplicate_flow(flow, name.strip()).id)

    def import_flow(self):
        if self.editor.flow is not None and not self.editor.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import flow", "", f"Flows (*{storage.EXPORT_EXT})")
        if not path:
            return
        try:
            flow = storage.import_flow(Path(path))
        except Exception as e:
            log.exception("Import failed")
            QMessageBox.warning(self, "Import failed", f"This file could not be imported.\n\n{e}")
            return
        self.refresh(flow.id)
        self.snackbar.show_message(f"Imported “{flow.name}” · check the monitor and steps")

    def export_flow(self):
        flow = self.editor.flow
        if not flow or not self.editor.maybe_save():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export flow", f"{flow.name}{storage.EXPORT_EXT}",
                                              f"Flows (*{storage.EXPORT_EXT})")
        if path:
            storage.export_flow(flow, Path(path))
            self.snackbar.show_message("Exported")

    def delete_flow(self):
        flow = self.editor.flow
        if flow and QMessageBox.question(self, "Delete flow",
                                         f"Delete “{flow.name}”? This cannot be undone.") == QMessageBox.Yes:
            storage.delete_flow(flow.id)
            self.editor.flow = None
            self.refresh()

    def _run_finished(self, result: engine.RunResult):
        self.editor.after_run()
        self.refresh(self.editor.flow.id if self.editor.flow else None)
        if result.status in (engine.FINISHED, engine.LIMIT):
            self.snackbar.show_message(result.message)

    # ---------- help ----------

    def show_tutorial(self):
        result = Tutorial(self).exec()
        settings = storage.load_settings()
        settings["tutorial_seen"] = True
        storage.save_settings(settings)
        if result:
            self.new_flow()

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(storage.logs_dir())))

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b> {__version__}<br><br>"
                          "Repeats a sequence of clicks for every item of a list on screen, "
                          "until the list is empty.<br><br>Everything runs locally: it only looks at the "
                          "screen and moves the mouse and keyboard.<br><br>"
                          "Press <b>F12</b> at any time to stop a run.<br><br>MIT License")

    def closeEvent(self, e):
        if self.editor.flow is not None and not self.editor.maybe_save():
            e.ignore()
            return
        self.editor.shutdown()
        super().closeEvent(e)
        QApplication.quit()
