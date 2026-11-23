"""Demo app to try AutoClicker Visual safely.

It shows a list of pending requests. Processing one takes several clicks in
successive windows, and the processed request disappears from the list:

    select first row -> Review -> Approve -> tick checkbox -> Confirm -> OK

Run:  python tools/demo_list_app.py [--items 10] [--delay 0.5]
"""

from __future__ import annotations

import argparse
import random
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

KINDS = ["Purchase order", "Holiday request", "Expense report", "Access request", "Document review"]
PEOPLE = ["Alice", "Bob", "Carmen", "David", "Elena", "Frank", "Grace", "Hugo"]


def make_items(n: int, seed: int = 7) -> list[str]:
    rnd = random.Random(seed)
    return [f"REQ-{1001 + i}   {rnd.choice(KINDS):<16}   {rnd.choice(PEOPLE)}" for i in range(n)]


class ReviewDialog(QDialog):
    def __init__(self, item: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review request")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{item.split()[0]}</b><br>Please review this request."))
        row = QHBoxLayout()
        approve, reject = QPushButton("Approve"), QPushButton("Reject")
        approve.clicked.connect(self.accept)
        reject.clicked.connect(self.reject)
        row.addWidget(approve)
        row.addWidget(reject)
        lay.addLayout(row)


class ConfirmDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm approval")
        lay = QVBoxLayout(self)
        self.check = QCheckBox("I have reviewed this request")
        self.ok = QPushButton("Confirm")
        self.ok.setEnabled(False)
        self.check.toggled.connect(self.ok.setEnabled)
        self.ok.clicked.connect(self.accept)
        lay.addWidget(self.check)
        lay.addWidget(self.ok)


class DemoWindow(QMainWindow):
    def __init__(self, items: list[str], delay_s: float = 0.0):
        super().__init__()
        self.delay_s = delay_s
        self.setWindowTitle("Demo Inbox")
        self.resize(640, 420)
        central = QWidget()
        central.setStyleSheet("background: #ffffff; color: #1f2937;")
        lay = QVBoxLayout(central)
        header = QLabel("Pending requests")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff; background: #2f5d8a; padding: 6px;")
        lay.addWidget(header)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { border: none; font-family: Consolas, monospace; font-size: 13px;"
                                " color: #1f2937; background: #ffffff; }"
                                "QListWidget::item { padding: 4px; }")
        self.list.addItems(items)
        lay.addWidget(self.list, 1)
        self.review = QPushButton("Review")
        self.review.clicked.connect(self.process_current)
        lay.addWidget(self.review, 0, Qt.AlignRight)
        self.setCentralWidget(central)

    def process_current(self):
        row = self.list.currentRow()
        if row < 0:
            QMessageBox.information(self, "Demo Inbox", "Select a request first.")
            return
        item = self.list.item(row).text()
        if ReviewDialog(item, self).exec() != QDialog.Accepted:
            return
        if ConfirmDialog(self).exec() != QDialog.Accepted:
            return
        QMessageBox.information(self, "Approved", f"{item.split()[0]} approved.")
        QTimer.singleShot(int(self.delay_s * 1000), lambda: self.list.takeItem(row))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.3, help="seconds before a processed item disappears")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)  # readable even with Windows in dark mode
    win = DemoWindow(make_items(args.items), args.delay)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
