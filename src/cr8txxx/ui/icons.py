# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""CR8TXXX's own line icons (inline SVG, drawn for this app, tinted from the palette), and
its app icon. SVGs are rendered at 2× so they stay sharp on Retina and 4K screens."""

from functools import cache

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer

from cr8txxx.ui import theme

_PATHS = {
    "files": '<path d="M9 2H4v12h8V5z"/><path d="M8 7v5M5.5 9.5h5"/>',
    "folder": '<path d="M2 4h4l1.5 1.5H14V13H2z"/><path d="M8 7.5v4M6 9.5h4"/>',
    "crate": '<path d="M2 6h12v7H2z"/><path d="M3 3h10v3H3z"/><path d="M6 9h4"/>',
    "edit": '<path d="M3 13l1-3.5L11 2.5 13.5 5 6.5 12z"/>',
    "relocate": '<circle cx="7" cy="7" r="4"/><path d="M10 10l3.5 3.5"/>',
    "refresh": '<path d="M13 8a5 5 0 1 1-1.5-3.6"/><path d="M12 1.5v3h-3"/>',
    "lock": '<rect x="3" y="7" width="10" height="7" rx="1"/>'
    '<path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/>',
    "search": '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5l3.5 3.5"/>',
    "tracks": '<path d="M3 4h10M3 8h10M3 12h6"/>',
    "missing": '<path d="M8 2l6.5 11.5h-13z"/><path d="M8 6.5v3.5M8 12v.2"/>',
    "hidden": '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/>'
    '<path d="M3 13L13 3"/>',
    "scan": '<path d="M2 8h2l1.5-4 3 8 2-6 1.5 2H14"/>',
    "plus": '<path d="M8 3v10M3 8h10"/>',
    "newsongs": '<path d="M6 12V3.5l7-1.5v8.5"/><circle cx="4.5" cy="12" r="1.5"/>'
    '<circle cx="11.5" cy="10.5" r="1.5"/>',
}


def _svg(name: str, color: str) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" '
        f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    ).encode()


@cache
def icon(name: str, color: str = theme.BLUE) -> QIcon:
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    out = QIcon()
    for size in (16, 32, 48, 64):
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        out.addPixmap(QPixmap.fromImage(image))
    return out


def draw_app_icon(size: int = 1024) -> QImage:
    """The app icon: a dark tile, a blue crate holding an orange-labelled record, "CR8"."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = size / 1024
    # macOS icon grid: an 824 px tile centred in 1024
    tile = QRectF(100 * u, 100 * u, 824 * u, 824 * u)
    p.setPen(QPen(QColor(theme.BEZEL), 6 * u))
    p.setBrush(QColor(theme.BODY))
    p.drawRoundedRect(tile, 185 * u, 185 * u)
    # the record, half out of the crate
    centre = QPointF(512 * u, 430 * u)
    p.setPen(QPen(QColor("#2a2d35"), 4 * u))
    p.setBrush(QColor("#050608"))
    p.drawEllipse(centre, 230 * u, 230 * u)
    p.setPen(QPen(QColor("#1d2027"), 3 * u))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for r in (200, 170, 140):
        p.drawEllipse(centre, r * u, r * u)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.ORANGE))
    p.drawEllipse(centre, 78 * u, 78 * u)
    p.setBrush(QColor(theme.BODY))
    p.drawEllipse(centre, 14 * u, 14 * u)
    # the crate's front
    front = QRectF(230 * u, 500 * u, 564 * u, 330 * u)
    p.setBrush(QColor(theme.PANEL))
    p.setPen(QPen(QColor(theme.BLUE), 26 * u))
    p.drawRoundedRect(front, 30 * u, 30 * u)
    handle = QPainterPath()
    handle.addRoundedRect(QRectF(422 * u, 548 * u, 180 * u, 40 * u), 20 * u, 20 * u)
    p.setPen(QPen(QColor(theme.BLUE), 14 * u))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(handle)
    # CR8
    f = QFont(theme.FONT_FAMILY)
    f.setPixelSize(round(170 * u))
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6 * u)
    p.setFont(f)
    p.setPen(QColor(theme.BRIGHT))
    p.drawText(QRectF(230 * u, 600 * u, 564 * u, 220 * u), Qt.AlignmentFlag.AlignCenter, "CR8")
    p.end()
    return image


@cache
def app_icon() -> QIcon:
    out = QIcon()
    for size in (32, 64, 128, 256, 512):
        out.addPixmap(QPixmap.fromImage(draw_app_icon(size)))
    return out
