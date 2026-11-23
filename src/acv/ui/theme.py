"""Design tokens (docs/design/ui-spec.md §2) and the stylesheet built from them.

Colours with alpha are written #AARRGGBB, which both QColor and Qt stylesheets understand.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor, QFont

# --- colour ---
BG = "#f4f5f8"
SIDEBAR = "#e9ebef"
TEXT = "#131a29"
MUTED = "#6c7486"
SEP = "#1f131a29"          # 12 % ink
FILL = "#0f131a29"         # 6 % ink
FILL_HOVER = "#1a131a29"   # 10 % ink
FILL_STRONG = "#26131a29"  # 15 % ink
GROUP = "#ffffff"
ACCENT = "#0a74f0"
ACCENT_HOVER = "#2a88f5"
ACCENT_TEXT = "#0a63d1"
ACCENT_TINT = "#1a0a74f0"  # 10 % accent
DANGER = "#f0445a"
WARN = "#e8960c"
WARN_TINT = "#24e8960c"
SNACK = "#131a29"
MONOGRAMS = ["#0a74f0", "#19a974", "#f08a24", "#8e5cf0", "#e8475f", "#1aa3b8"]

# --- shape ---
R_PILL = 7
R_ROW = 8
R_GROUP = 10
R_THUMB = 8
R_CARD = 18

# --- type ---
TEXT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "DejaVu Sans", "sans-serif"]
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Segoe UI", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace"]
BASE_PX = 13

# --- motion ---
SPRING = QEasingCurve(QEasingCurve.OutBack)
SPRING.setOvershoot(1.2)  # gentle settle, not a bounce
SMOOTH = QEasingCurve(QEasingCurve.OutCubic)
_animations = True


def set_animations(enabled: bool) -> None:
    global _animations
    _animations = enabled


def animations() -> bool:
    return _animations


def color(value: str, alpha: float | None = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def font(px: int = BASE_PX, weight: QFont.Weight = QFont.Normal, display: bool = False, mono: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else DISPLAY_FAMILIES if display else TEXT_FAMILIES)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _families(names: list[str]) -> str:
    return ", ".join(f'"{n}"' if " " in n else n for n in names)


def stylesheet() -> str:
    """QSS for the standard widgets. Custom-painted widgets read the tokens above directly."""
    return f"""
* {{ font-family: {_families(TEXT_FAMILIES)}; font-size: {BASE_PX}px; color: {TEXT}; }}
QMainWindow, QDialog, QWizard, QWizardPage, QMessageBox, QInputDialog {{ background: {BG}; }}
QWidget#editor, QWidget#emptyState, QScrollArea#editorScroll, QWidget#editorInner {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-family: {_families(DISPLAY_FAMILIES)}; font-size: 24px; font-weight: 700; }}
QLabel#sideTitle {{ font-family: {_families(DISPLAY_FAMILIES)}; font-size: 20px; font-weight: 700; }}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#caption {{ color: {MUTED}; font-weight: 600; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QLabel#mono {{ font-family: {_families(MONO_FAMILIES)}; font-size: 12px; color: {MUTED}; }}
QLabel#thumb {{ background: #ffffff; border: 1px solid {SEP}; border-radius: 6px; padding: 2px; }}
QLabel#error {{ color: {DANGER}; }}

QFrame#card {{ background: {GROUP}; border: 1px solid {SEP}; border-radius: {R_CARD}px; }}
QFrame#group {{ background: {GROUP}; border: 1px solid {SEP}; border-radius: {R_GROUP}px; }}
QFrame#sep {{ background: {SEP}; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{
    background: {FILL}; border: none; border-radius: {R_PILL}px; padding: 6px 14px;
    font-weight: 600; min-height: 18px;
}}
QPushButton:hover {{ background: {FILL_HOVER}; }}
QPushButton:pressed {{ background: {FILL_STRONG}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton:default, QPushButton[variant="filled"] {{ background: {ACCENT}; color: #ffffff; }}
QPushButton:default:hover, QPushButton[variant="filled"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[variant="link"] {{ background: transparent; color: {ACCENT_TEXT}; text-align: left; padding: 0; font-weight: 600; }}
QPushButton[variant="link"]:hover {{ color: {ACCENT}; }}
QPushButton[variant="quietLink"] {{ background: transparent; color: {MUTED}; text-align: left; padding: 0; font-weight: 500; }}
QPushButton[variant="quietLink"]:hover {{ color: {TEXT}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: #ffffff; border: 1px solid {SEP}; border-radius: {R_PILL}px; padding: 3px 8px; min-height: 22px;
    selection-background-color: {ACCENT}; selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#search {{ background: {FILL}; border: 1px solid transparent; border-radius: 9px; padding: 6px 10px; }}
QLineEdit#search:focus {{ background: #ffffff; border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{ background: #ffffff; border: 1px solid {SEP}; selection-background-color: {ACCENT_TINT}; selection-color: {TEXT}; outline: 0; }}

QListView, QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget#steps {{ background: {GROUP}; border: 1px solid {SEP}; border-radius: {R_GROUP}px; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {FILL_STRONG}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #40131a29; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {FILL_STRONG}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: #ffffff; border: 1px solid {SEP}; border-radius: {R_ROW}px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {SEP}; margin: 4px 8px; }}
QToolTip {{ background: {SNACK}; color: #ffffff; border: none; border-radius: 6px; padding: 5px 8px; }}

QGroupBox {{ background: {GROUP}; border: 1px solid {SEP}; border-radius: {R_GROUP}px; margin-top: 22px; padding: 12px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 4px; padding: 0 2px; color: {MUTED}; font-weight: 600; }}
QCheckBox {{ spacing: 8px; }}
"""
