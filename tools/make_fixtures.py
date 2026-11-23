"""Regenerate tests/fixtures/*.png from the demo app (no real screenshots are ever used).

Run:  python tools/make_fixtures.py   (works headless with QT_QPA_PLATFORM=offscreen)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from demo_list_app import DemoWindow, ReviewDialog, make_items  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
DESKTOP = (1280, 800)
WIN_POS = (120, 90)
DIALOG_POS = (420, 300)


def to_bgr(widget) -> np.ndarray:
    img = widget.grab().toImage().convertToFormat(QImage.Format_RGB888)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine())
    return cv2.cvtColor(arr[:, : img.width() * 3].reshape(img.height(), img.width(), 3), cv2.COLOR_RGB2BGR)


def desktop(*layers) -> np.ndarray:
    screen = np.full((DESKTOP[1], DESKTOP[0], 3), (140, 100, 50), np.uint8)
    for img, (x, y) in layers:
        screen[y:y + img.shape[0], x:x + img.shape[1]] = img
    return screen


def rect_in(widget, window, offset) -> list[int]:
    p = widget.mapTo(window, QPoint(0, 0))
    return [offset[0] + p.x(), offset[1] + p.y(), widget.width(), widget.height()]


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("DejaVu Sans", 10))
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}

    full = DemoWindow(make_items(8))
    full.show()
    app.processEvents()
    header = full.findChild(QLabel)
    meta["anchor"] = rect_in(header, full, WIN_POS)
    first = full.list.visualItemRect(full.list.item(0))
    lp = full.list.viewport().mapTo(full, QPoint(0, 0))
    meta["first_row"] = [WIN_POS[0] + lp.x() + first.x(), WIN_POS[1] + lp.y() + first.y(), first.width(), first.height()]
    full_img = to_bgr(full)
    cv2.imwrite(str(OUT / "screen_list_full.png"), desktop((full_img, WIN_POS)))

    full.list.takeItem(0)
    app.processEvents()
    cv2.imwrite(str(OUT / "screen_list_next.png"), desktop((to_bgr(full), WIN_POS)))

    empty = DemoWindow([])
    empty.show()
    app.processEvents()
    cv2.imwrite(str(OUT / "screen_list_empty.png"), desktop((to_bgr(empty), WIN_POS)))

    dialog = ReviewDialog(make_items(1)[0])
    dialog.resize(260, 110)
    dialog.show()
    app.processEvents()
    approve = [b for b in dialog.findChildren(QPushButton) if b.text() == "Approve"][0]
    meta["approve_button"] = rect_in(approve, dialog, DIALOG_POS)
    cv2.imwrite(str(OUT / "screen_review_dialog.png"), desktop((full_img, WIN_POS), (to_bgr(dialog), DIALOG_POS)))

    (OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Fixtures written to {OUT}")


if __name__ == "__main__":
    main()
