"""Draw the app icon (src/acv/resources/icon.png + installer/icon.ico). Run once; outputs are committed."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#1e40af"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    p.fillPath(path, QBrush(grad))
    # list rows
    p.setPen(Qt.NoPen)
    for i, w in enumerate((150, 120, 135)):
        p.setBrush(QColor(255, 255, 255, 90 if i else 150))
        p.drawRoundedRect(QRectF(40, 52 + i * 44, w, 26), 8, 8)
    # target ring
    p.setPen(QPen(QColor("#facc15"), 10))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(150, 160), 34, 34)
    # cursor
    arrow = QPolygonF([QPointF(x, y) for x, y in
                       ((150, 160), (150, 232), (167, 214), (182, 246), (198, 239), (183, 207), (207, 205))])
    p.setPen(QPen(QColor("#0f172a"), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor("white"))
    p.drawPolygon(arrow)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    (ROOT / "installer").mkdir(exist_ok=True)
    draw(256).save(str(ROOT / "src" / "acv" / "resources" / "icon.png"))
    assert draw(256).save(str(ROOT / "installer" / "icon.ico")), "ICO writer unavailable"
    print("icon written")
