"""Entry point: DPI awareness first, then logging, then the Qt application."""

import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

import acv
from acv import APP_NAME, __version__, desktop, storage

log = logging.getLogger("acv")


def setup_logging() -> None:
    handler = logging.handlers.TimedRotatingFileHandler(
        storage.logs_dir() / "acv.log", when="midnight", backupCount=14, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr:  # no console in the packaged app
        root.addHandler(logging.StreamHandler())


def main() -> None:
    desktop.set_dpi_awareness()  # before any window or capture, so all coordinates are physical pixels
    setup_logging()
    log.info("%s %s starting", APP_NAME, __version__)

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from acv.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # our windows are hidden during captures/runs; closing a helper window then must not quit the app
    app.setQuitOnLastWindowClosed(False)
    resources = Path(acv.__file__).resolve().parent / "resources"  # also right inside the PyInstaller bundle
    app.setWindowIcon(QIcon(str(resources / "icon.png")))
    app.setStyleSheet((resources / "style.qss").read_text(encoding="utf-8"))

    def on_error(exc_type, exc, tb):
        log.error("Unexpected error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        box = QMessageBox(QMessageBox.Critical, "Something went wrong",
                          "An unexpected error happened. Nothing else will be clicked.\n\n"
                          f"{exc_type.__name__}: {exc}")
        logs = box.addButton("Open logs folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is logs:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(storage.logs_dir())))

    sys.excepthook = on_error
    threading.excepthook = lambda a: log.error("Error in thread %s", a.thread,
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    window = MainWindow()
    window.show()
    if not storage.load_settings().get("tutorial_seen"):
        QTimer.singleShot(300, window.show_tutorial)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
