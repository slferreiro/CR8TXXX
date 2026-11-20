# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The track tables: a model over a list of Tracks, a filter for the search box, and the
delegate that draws the colour strip and star ratings. Kept light so a library of tens of
thousands of tracks sorts and searches without waiting."""

import contextlib
import re
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    QUrl,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from cr8txxx.db.tracks import Track
from cr8txxx.ui import theme

MIME = "application/x-cr8txxx-track-ids"

# Display order: (key, heading). "path" is the file's location; "color" the strip.
COLUMNS = [
    ("color", ""),
    ("artist", "Artist"),
    ("title", "Title"),
    ("album", "Album"),
    ("genre", "Genre"),
    ("bpm", "BPM"),
    ("key", "Key"),
    ("duration", "Time"),
    ("rating", "Rating"),
    ("check", "Check"),
    ("problem", "Problem"),
    ("datetime_added", "Added"),
    ("filetype", "Type"),
    ("path", "Location"),
    ("album_artist", "Album Artist"),
    ("composer", "Composer"),
    ("grouping", "Grouping"),
    ("year", "Year"),
    ("tracknumber", "#"),
    ("bitrate", "kbps"),
    ("comment", "Comment"),
]
KEYS = [k for k, _ in COLUMNS]
HEADINGS = [h for _, h in COLUMNS]
NUMERIC = {"bpm", "duration", "bitrate", "rating", "color"}
RIGHT = {"bpm", "duration", "bitrate", "year", "tracknumber"}
SEARCHED = ("artist", "title", "album", "album_artist", "genre", "composer", "grouping",
            "comment", "key")  # fmt: skip
EXTRA = {
    "check",
    "problem",
    "album_artist",
    "composer",
    "grouping",
    "year",
    "tracknumber",
    "bitrate",
    "comment",
}
LIBRARY_HIDDEN = EXTRA
CRATE_HIDDEN = EXTRA | {"album", "genre", "key", "rating", "datetime_added", "filetype", "path"}
STRIP = 6  # px, before text scaling

# Key colours on the Camelot wheel (1–12), the way DJ software tints keys
_WHEEL = ["#5ee0d6", "#5ef0a0", "#8ff05e", "#d8f05e", "#f0c85e", "#f0965e",
          "#f06e6e", "#f06eb0", "#d06ef0", "#9a7ef0", "#6e96f0", "#5ec0f0"]  # fmt: skip
_CAMELOT = {
    "B": 1, "F#": 2, "Gb": 2, "C#": 3, "Db": 3, "G#": 4, "Ab": 4, "D#": 5, "Eb": 5, "A#": 6,
    "Bb": 6, "F": 7, "C": 8, "G": 9, "D": 10, "A": 11, "E": 12,
    "G#m": 1, "Abm": 1, "D#m": 2, "Ebm": 2, "A#m": 3, "Bbm": 3, "Fm": 4, "Cm": 5, "Gm": 6,
    "Dm": 7, "Am": 8, "Em": 9, "Bm": 10, "F#m": 11, "Gbm": 11, "C#m": 12, "Dbm": 12,
}  # fmt: skip

Index = QModelIndex | QPersistentModelIndex

BAD = {"damaged", "unreadable"}
WARN = {"suspect"}
CHECK_WORDS = {"damaged": "DAMAGED", "unreadable": "Unreadable", "suspect": "Suspect",
               "ok": "OK", "unchecked": "Not checked",
               "verified": "Verified ✓"}  # fmt: skip
VERIFIED = "verified"
BAD_ROW = "#3a1216"
BAD_TEXT = "#ff6b6b"


def key_color(key: object) -> QColor | None:
    text = str(key or "").strip()
    m = re.fullmatch(r"(\d{1,2})\s*([ABdm])", text)
    if m:  # Camelot (8A) or Open Key (1m, which is Camelot 8A)
        n = int(m.group(1))
        n = (n + 6) % 12 + 1 if m.group(2) in "dm" else n
    else:
        n = _CAMELOT.get(text.replace("min", "m").replace(" ", ""), 0)
    return QColor(_WHEEL[(n - 1) % 12]) if n else None


def clock(seconds: object) -> str:
    try:
        s = int(float(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if not s:
        return ""
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{s // 60}:{s % 60:02d}"


def show(key: str, value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        if key == "duration":
            return clock(value)
        if key == "bpm":
            return f"{float(value):.1f}" if float(value) else ""  # type: ignore[arg-type]
        if key == "bitrate":
            return str(value) if int(value) else ""  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return ""
    if key == "rating":
        return ""  # drawn as stars
    if key == "datetime_added":
        return str(value)[:10]
    if key == "color":
        return ""
    return str(value)


class TrackModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Track] = []
        self._search: list[str] = []
        self.number_font = theme.numeric_font(theme.font())
        self.checks: dict[str, str] = {}  # path → the damage scan's status
        self.details: dict[str, str] = {}  # path → what's wrong, in a line

    def set_checks(self, statuses: dict[str, str], details: dict[str, str]) -> None:
        """The damage scan's results (red: damaged/unreadable; amber: suspect)."""
        self.checks, self.details = statuses, details
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(KEYS) - 1))

    def status(self, t: Track) -> str:
        return self.checks.get(t.path, "")

    def set_tracks(self, rows: list[Track]) -> None:
        self.beginResetModel()
        self.rows = rows
        self._search = [
            " ".join(str(t.get(k) or "") for k in SEARCHED).casefold() + " " + t.path.casefold()
            for t in rows
        ]
        self.endResetModel()

    def restyle(self) -> None:
        """The text size changed."""
        self.number_font = theme.numeric_font(theme.font())
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(KEYS) - 1))

    def search_text(self, row: int) -> str:
        return self._search[row]

    def total_seconds(self) -> int:
        total = 0
        for t in self.rows:
            with contextlib.suppress(TypeError, ValueError):
                total += int(float(t.get("duration") or 0))  # type: ignore[arg-type]
        return total

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(KEYS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADINGS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _align(KEYS[section])
        return None

    def track(self, row: int) -> Track:
        return self.rows[row]

    def data(self, index: Index, role: int = 0) -> Any:
        if not index.isValid():
            return None
        t = self.rows[index.row()]
        key = KEYS[index.column()]
        status = self.checks.get(t.path, "")
        value: object = (
            t.path if key == "path" else status if key in ("check", "problem") else t.get(key)
        )
        R = Qt.ItemDataRole
        if role == R.DisplayRole:
            if key == "check":
                return CHECK_WORDS.get(status, "")
            if key == "problem":
                bad = status and status not in ("ok", VERIFIED)
                return self.details.get(t.path, "") if bad else ""
            return show(key, value)
        if role == R.BackgroundRole and not t.missing:
            if status in BAD:
                return QBrush(QColor(BAD_ROW))
            return None  # suspect: amber text only, so only damage stands out
        if role == R.UserRole:  # for sorting
            if key in NUMERIC:
                try:
                    return float(value or 0)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return 0.0
            return str(value or "").casefold()
        if role == R.TextAlignmentRole:
            return _align(key)
        if role == R.FontRole:
            if key == "check" and status in BAD:
                f = QFont(theme.font())
                f.setBold(True)
                return f
            if t.missing:
                f = QFont(theme.font())
                f.setItalic(True)
                return f
            return self.number_font if key in RIGHT else None
        if role == R.ForegroundRole:
            if t.missing:
                return QBrush(QColor(theme.RED))
            if status in BAD:
                return QBrush(QColor(BAD_TEXT))
            if status in WARN:
                return QBrush(QColor(theme.AMBER))
            if status == VERIFIED and key == "check":
                return QBrush(QColor(theme.GREEN))
            if key == "key":
                color = key_color(value)
                return QBrush(color) if color else None
            if key in ("album", "genre", "datetime_added", "filetype", "path"):
                return QBrush(QColor(theme.DIM2))
            if key == "title":
                return QBrush(QColor(theme.BRIGHT))
            return None
        if role == R.ToolTipRole:
            if t.missing:
                return f"File missing:\n{t.path}"
            if status in BAD or status in WARN or status == VERIFIED:
                word = CHECK_WORDS[status]
                return f"{word}: {self.details.get(t.path, '')}\n{t.path}"
            if key == "path":
                return t.path
            return None
        if role == R.UserRole + 1:  # the delegate: colour strip / rating
            if key == "color":
                return None if value is None else QColor(f"#{int(value) & 0xFFFFFF:06x}")  # type: ignore[call-overload]
            if key == "rating":
                try:
                    return int(value or 0)  # type: ignore[call-overload]
                except (TypeError, ValueError):
                    return 0
        return None

    def flags(self, index: Index) -> Qt.ItemFlag:
        base = super().flags(index)
        return base | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else base

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [MIME]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:  # noqa: N802
        ids = sorted({self.rows[i.row()].id for i in indexes if i.isValid()})
        mime = QMimeData()
        mime.setData(MIME, ",".join(map(str, ids)).encode())
        # The files themselves, for dropping into Finder or another app (copied, never moved)
        rows = {i.row() for i in indexes if i.isValid()}
        files = [self.rows[r].path for r in sorted(rows) if not self.rows[r].missing]
        mime.setUrls([QUrl.fromLocalFile(f) for f in files])
        return mime

    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction


def _align(key: str) -> int:
    v = Qt.AlignmentFlag.AlignVCenter
    if key in RIGHT:
        return int(v | Qt.AlignmentFlag.AlignRight)
    if key == "rating":
        return int(v | Qt.AlignmentFlag.AlignHCenter)
    return int(v | Qt.AlignmentFlag.AlignLeft)


class TrackDelegate(QStyledItemDelegate):
    """Draws the colour strip at the row's left edge and the rating as stars."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        key = KEYS[index.column()]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else None
        if style:  # the row's background (scan marks) and selection, across the whole cell
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter,
                                opt.widget)  # fmt: skip
        if key not in ("color", "rating"):
            if style:  # the text, inset from the cell's edges
                pad = theme.px(6)
                opt.rect = option.rect.adjusted(pad, 0, -pad, 0)
                opt.backgroundBrush = QBrush()
                opt.palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
                style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
            else:
                super().paint(painter, option, index)
            return
        value = index.data(Qt.ItemDataRole.UserRole + 1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        if key == "color":
            if isinstance(value, QColor):
                painter.fillRect(QRectF(r.left(), r.top() + 1, theme.px(STRIP), r.height() - 2),
                                 value)  # fmt: skip
        else:
            n = int(value or 0)
            size = min(r.height() * 0.62, r.width() / 5.6)
            total = size * 5 + size * 0.15 * 4
            x = r.center().x() - total / 2
            y = r.center().y() - size / 2
            f = QFont(theme.font())
            f.setPixelSize(max(1, round(size)))
            painter.setFont(f)
            for i in range(5):
                painter.setPen(QColor(theme.ORANGE if i < n else theme.EMPTY_STAR))
                painter.drawText(QRectF(x, y, size, size), Qt.AlignmentFlag.AlignCenter,
                                 "★" if i < n else "☆")  # fmt: skip
                x += size * 1.15
        painter.restore()


class TrackFilter(QSortFilterProxyModel):
    """Every word typed must be found in the track (artist, title, album, … or its path)."""

    def __init__(self) -> None:
        super().__init__()
        self._words: list[str] = []
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self._words = text.casefold().split()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row: int, parent: Index) -> bool:  # noqa: N802
        if not self._words:
            return True
        source = self.sourceModel()
        assert isinstance(source, TrackModel)
        text = source.search_text(row)
        return all(w in text for w in self._words)


def files_from_mime(mime: QMimeData) -> list[str]:
    """Files and folders dragged in from Finder (not tracks dragged inside CR8TXXX)."""
    if mime.hasFormat(MIME) or not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]


def ids_from_mime(mime: QMimeData) -> list[int]:
    if not mime.hasFormat(MIME):
        return []
    raw = bytes(mime.data(MIME).data()).decode()
    return [int(x) for x in raw.split(",") if x]
