# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""CR8TXXX's look: the palette of the TwrRcrds Mixxx skin (its style.qss header), applied to
the whole app as a Qt palette and one style sheet. Every size is the base size times the
text scale, so View › Text Size grows everything together (for big un-scaled 4K displays).

Only the skin's colours are used, none of its image files (the skin is GPL-2.0)."""

import contextlib

from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

BODY = "#0d0e11"
PANEL = "#15171c"
PANEL2 = "#1b1d23"
LIST = "#101216"
ALT = "#14161b"
BEZEL = "#2a2d35"
LINE = "#23262d"
BORDER = "#343843"
BUTTON = "#1d2027"
HOVER = "#55596a"
INPUT = "#0a0b0e"
TEXT = "#d6d9df"
BRIGHT = "#f1f3f7"
DIM = "#7d8390"
DIM2 = "#a6acb8"
EMPTY_STAR = "#4a4f5c"
BLUE = "#25a8ff"
SELECT = "#0f4d7a"
ACTIVE = "#0f3350"
CRATE_SELECT = "#1b2a38"
ORANGE = "#ff8a1f"
AMBER = "#ffb13d"
GREEN = "#3ddc84"
RED = "#ff3d3d"

FONT_FAMILY = "Helvetica Neue"
BASE_PX = 13
SCALES = [0.85, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8]

_scale = 1.0


def scale() -> float:
    return _scale


def auto_scale() -> float:
    """The starting text size: 1.25 on a screen wider than 2560 logical pixels (a 4K display
    at its full resolution), else 1.0. macOS's usual Retina scaling needs no change."""
    screen = QGuiApplication.primaryScreen()
    if screen and screen.availableGeometry().width() > 2560:
        return 1.25
    return 1.0


def px(n: float) -> int:
    return max(1, round(n * _scale))


def font(size: float = BASE_PX, bold: bool = False, spacing: float = 0) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px(size))
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing * _scale)
    return f


def numeric_font(base: QFont) -> QFont:
    """Tabular figures, so numbers line up in their columns."""
    f = QFont(base)
    with contextlib.suppress(AttributeError, TypeError):  # older Qt: no font features
        f.setFeature(QFont.Tag("tnum"), 1)
    return f


def row_height() -> int:
    return round(QFontMetrics(font()).height() * 1.7)


def _palette() -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    for role, color in (
        (roles.Window, BODY),
        (roles.WindowText, TEXT),
        (roles.Base, LIST),
        (roles.AlternateBase, ALT),
        (roles.Text, TEXT),
        (roles.Button, BUTTON),
        (roles.ButtonText, TEXT),
        (roles.BrightText, BRIGHT),
        (roles.Highlight, SELECT),
        (roles.HighlightedText, "#ffffff"),
        (roles.ToolTipBase, PANEL2),
        (roles.ToolTipText, TEXT),
        (roles.PlaceholderText, DIM),
        (roles.Link, BLUE),
        (roles.Mid, BORDER),
        (roles.Dark, BODY),
        (roles.Light, BEZEL),
    ):
        p.setColor(role, QColor(color))
    for role in (roles.Text, roles.WindowText, roles.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(DIM))
    return p


def style_sheet() -> str:
    s = px
    return f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BODY}; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER}; padding: {s(4)}px; }}

#Header {{ background: {ALT}; border-bottom: 1px solid {BEZEL}; }}
#Banner {{ background: #2a1a08; color: {AMBER}; border-bottom: 1px solid {ORANGE};
           padding: {s(6)}px {s(12)}px; font-weight: bold; }}

QToolButton#ToolBarButton, QPushButton#SmallButton {{
    background: {BUTTON}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    color: {DIM2}; font-weight: bold; padding: {s(4)}px {s(10)}px; }}
QToolButton#ToolBarButton:hover, QPushButton#SmallButton:hover {{
    border-color: {HOVER}; color: #ffffff; }}
QToolButton#ToolBarButton:pressed, QPushButton#SmallButton:pressed {{
    background: {ACTIVE}; border-color: {BLUE}; color: #ffffff; }}
QToolButton#ToolBarButton:disabled, QPushButton#SmallButton:disabled {{
    color: {EMPTY_STAR}; border-color: {LINE}; }}

QPushButton#Tab {{
    background: {BUTTON}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    color: {DIM2}; font-weight: bold; padding: {s(4)}px {s(11)}px; }}
QPushButton#Tab:hover {{ border-color: {HOVER}; color: #ffffff; }}
QPushButton#Tab:checked {{ background: {ACTIVE}; border-color: {BLUE}; color: #ffffff; }}

QFrame#Pane {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: {s(4)}px; }}
QFrame#Pane[dropTarget="true"] {{ border: 1px solid {BLUE}; }}
#PaneHeader {{ border-bottom: 1px solid {LINE}; }}
QLabel#PaneTitle {{ color: {DIM}; }}
QLabel#CrateTag {{ color: {ORANGE}; }}
QLabel#Strong {{ color: {BRIGHT}; font-weight: bold; }}
QLabel#Dim {{ color: {DIM}; }}
QLabel#EmptyTitle {{ color: {BRIGHT}; font-weight: bold; }}
QLabel#EmptyText {{ color: {DIM2}; }}

QTableView {{
    background: {LIST}; alternate-background-color: {ALT}; border: none;
    gridline-color: {LINE}; selection-background-color: {SELECT}; selection-color: #ffffff;
    outline: none; }}
QHeaderView {{ background: {ALT}; border: none; }}
QHeaderView::section {{
    background: {ALT}; color: {DIM2}; font-weight: bold; border: none;
    border-right: 1px solid {LINE}; border-bottom: 1px solid {LINE};
    padding: {s(4)}px {s(6)}px; }}
QHeaderView::section:hover {{ color: #ffffff; }}

QListWidget#Crates {{ background: {LIST}; border: none; outline: none; }}

QLineEdit {{
    background: {INPUT}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    padding: {s(4)}px {s(7)}px; selection-background-color: {SELECT}; }}
QLineEdit:focus {{ border-color: {BLUE}; color: #ffffff; }}

QPushButton {{
    background: {BUTTON}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    padding: {s(5)}px {s(14)}px; color: {TEXT}; }}
QPushButton:hover {{ border-color: {HOVER}; color: #ffffff; }}
QPushButton:default {{ border-color: {BLUE}; }}
QPushButton:disabled {{ color: {DIM}; border-color: {LINE}; }}
QComboBox {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    padding: {s(4)}px {s(8)}px; }}
QComboBox QAbstractItemView {{ background: {PANEL2}; selection-background-color: {SELECT}; }}

QPushButton#Primary {{ background: {ACTIVE}; border: 1px solid {BLUE}; color: #ffffff;
    font-weight: bold; padding: {s(6)}px {s(16)}px; }}
QPushButton#Primary:hover {{ background: #154569; }}
QPushButton#Primary:disabled {{ background: {BUTTON}; border-color: {LINE}; color: {DIM}; }}
#ScanBar {{ border-bottom: 1px solid {LINE}; background: {PANEL}; }}
QLabel#ScanSummary {{ color: {DIM2}; }}
QLabel#ScanBad {{ color: #ff6b6b; font-weight: bold; }}
QProgressBar {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: {s(4)}px;
    color: {TEXT}; text-align: center; min-height: {s(18)}px; }}
QProgressBar::chunk {{ background: {SELECT}; border-radius: {s(3)}px; }}

QMenu {{ background: {PANEL2}; border: 1px solid {BORDER}; padding: {s(4)}px 0; }}
QMenu::item {{ padding: {s(5)}px {s(22)}px; }}
QMenu::item:selected {{ background: {SELECT}; color: #ffffff; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: {s(4)}px {s(8)}px; }}

QSplitter::handle {{ background: {BODY}; }}
QSplitter::handle:hover {{ background: {BLUE}; }}
QSplitter::handle:horizontal {{ width: {s(6)}px; }}
QSplitter::handle:vertical {{ height: {s(6)}px; }}

QScrollBar:vertical {{ background: {LIST}; width: {s(12)}px; margin: 0;
    border-left: 1px solid {LINE}; }}
QScrollBar:horizontal {{ background: {LIST}; height: {s(12)}px; margin: 0;
    border-top: 1px solid {LINE}; }}
QScrollBar::handle {{ background: {BORDER}; border-radius: {s(4)}px; margin: {s(2)}px; }}
QScrollBar::handle:vertical {{ min-height: {s(24)}px; }}
QScrollBar::handle:horizontal {{ min-width: {s(24)}px; }}
QScrollBar::handle:hover {{ background: {HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{ background: {ALT}; border-top: 1px solid {BEZEL}; color: {DIM}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {ALT}; }}
QMenuBar::item:selected {{ background: {SELECT}; }}
"""


def apply(app: QApplication, text_scale: float) -> None:
    """The look, at this text size (1.0 = 13 px base)."""
    global _scale
    _scale = text_scale
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setFont(font())
    app.setStyleSheet(style_sheet())


def fit_to_screen(widget: QWidget, width: float, height: float, min_w: int = 0,
                  min_h: int = 0) -> None:  # fmt: skip
    """Size a window or dialog as a share of its screen's free area."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    w = max(min_w, min(area.width(), round(area.width() * width)))
    h = max(min_h, min(area.height(), round(area.height() * height)))
    widget.resize(w, h)
