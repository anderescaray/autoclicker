"""Main window: the list of flows and what you can do with them."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, storage
from ..desktop import list_monitors
from ..model import IMAGE_STEPS, Flow
from .dialogs import RunDialog
from .flow_editor import FlowEditor
from .run_controller import RunController
from .tutorial import Tutorial

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(820, 520)
        self.editor: FlowEditor | None = None
        self.run_controller = RunController(self)
        self.run_controller.finished.connect(lambda _: self.refresh())

        central = QWidget()
        lay = QVBoxLayout(central)
        title = QLabel("Your flows")
        title.setObjectName("heading")
        lay.addWidget(title)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Name", "Steps", "Last run"])
        self.table.setRootIsDecorated(False)
        self.table.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit_flow())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.table, 1)
        self.empty_hint = QLabel("No flows yet. Click <b>New</b> to create one, or open <b>Help → Tutorial</b>.")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty_hint)

        row = QHBoxLayout()
        self.buttons = {}
        for key, text, slot in (("new", "New", self.new_flow), ("edit", "Edit", self.edit_flow),
                                ("run", "▶ Run", self.run_flow), ("dup", "Duplicate", self.duplicate_flow),
                                ("import", "Import…", self.import_flow), ("export", "Export…", self.export_flow),
                                ("delete", "Delete", self.delete_flow)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            self.buttons[key] = b
            row.addWidget(b)
            if key == "run":
                b.setObjectName("primary")
            if key == "dup":
                row.addStretch()
        lay.addLayout(row)
        self.setCentralWidget(central)

        help_menu = self.menuBar().addMenu("&Help")
        for text, slot in (("Tutorial", self.show_tutorial), ("Open logs folder", self.open_logs),
                           (f"About {APP_NAME}", self.about)):
            action = QAction(text, self)
            action.triggered.connect(slot)
            help_menu.addAction(action)
        self.refresh()

    # ---------- list ----------

    def refresh(self, select_id: str | None = None):
        current = select_id or (self.current().id if self.current() else None)
        self.table.clear()
        for flow in storage.list_flows():
            item = QTreeWidgetItem([flow.name, str(len(flow.steps)), flow.last_run or "Never"])
            item.setData(0, Qt.UserRole, flow.id)
            self.table.addTopLevelItem(item)
            if flow.id == current:
                self.table.setCurrentItem(item)
        if self.table.currentItem() is None and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        self.empty_hint.setVisible(self.table.topLevelItemCount() == 0)
        self._update_buttons()

    def current(self) -> Flow | None:
        item = self.table.currentItem()
        if not item:
            return None
        try:
            return storage.load_flow(item.data(0, Qt.UserRole))
        except Exception:
            log.exception("Cannot load flow")
            QMessageBox.warning(self, "Cannot open flow", "This flow could not be read. See the log for details.")
            return None

    def _update_buttons(self):
        has = self.table.currentItem() is not None
        for key in ("edit", "run", "dup", "export", "delete"):
            self.buttons[key].setEnabled(has)

    # ---------- actions ----------

    def new_flow(self):
        name, ok = QInputDialog.getText(self, "New flow", "Name of the flow (e.g. 'Approve requests'):")
        if not ok or not name.strip():
            return
        flow = Flow(name=name.strip())
        monitors = list_monitors()
        if len(monitors) == 1:
            flow.monitor = monitors[0]
        self._open_editor(flow, is_new=True)
        if len(monitors) > 1:
            self.editor.choose_monitor()

    def edit_flow(self):
        flow = self.current()
        if flow:
            self._open_editor(flow)

    def _open_editor(self, flow: Flow, is_new: bool = False):
        self.editor = FlowEditor(flow, self.run_controller, is_new)
        self.editor.saved.connect(lambda: self.refresh(flow.id))
        self.editor.closed.connect(self._editor_closed)
        self.setEnabled(False)  # one thing at a time: no deleting a flow while it is being edited
        self.editor.show()

    def _editor_closed(self):
        self.editor = None
        self.setEnabled(True)
        self.refresh()

    def run_flow(self):
        flow = self.current()
        if not flow:
            return
        if not flow.is_ready():
            QMessageBox.information(self, "Not ready", "This flow needs an anchor, a first row and at least one "
                                                       "step. Open it with Edit first.")
            return
        if not RunDialog(flow, self).exec():
            return
        try:
            names = {flow.anchor_image, flow.first_row.empty_sample}
            names |= {s.image for s in flow.steps if s.type in IMAGE_STEPS}
            images = {n: storage.load_flow_image(flow, n) for n in names if n}
        except (OSError, ValueError):
            log.exception("Missing flow image")
            QMessageBox.warning(self, "Flow damaged", "Some images of this flow are missing. Record it again.")
            return
        storage.save_flow(flow)  # keep the run options chosen in the dialog
        self.run_controller.start(flow, images, parent=self)

    def duplicate_flow(self):
        flow = self.current()
        if not flow:
            return
        name, ok = QInputDialog.getText(self, "Duplicate", "Name of the copy:", text=f"{flow.name} (copy)")
        if ok and name.strip():
            self.refresh(storage.duplicate_flow(flow, name.strip()).id)

    def import_flow(self):
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
        QMessageBox.information(self, "Imported", f"Imported '{flow.name}'. Open it with Edit and check the "
                                                  "monitor and the steps before running it on this computer.")

    def export_flow(self):
        flow = self.current()
        if not flow:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export flow", f"{flow.name}{storage.EXPORT_EXT}",
                                              f"Flows (*{storage.EXPORT_EXT})")
        if path:
            storage.export_flow(flow, Path(path))

    def delete_flow(self):
        flow = self.current()
        if flow and QMessageBox.question(self, "Delete flow",
                                         f"Delete '{flow.name}'? This cannot be undone.") == QMessageBox.Yes:
            storage.delete_flow(flow.id)
            self.refresh()

    # ---------- help ----------

    def show_tutorial(self):
        tutorial = Tutorial(self)
        result = tutorial.exec()
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
        if self.editor is not None:
            self.editor.close()
            if self.editor is not None:  # the user cancelled closing the editor
                e.ignore()
                return
        super().closeEvent(e)
        QApplication.quit()
