# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""A framed pane holding a track table: a header row (title, counts, controls), the table,
and an empty-state message. Used for the library (left) and the selected crate (right)."""

from collections.abc import Callable

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from cr8txxx.db.tracks import Track
from cr8txxx.ui import theme
from cr8txxx.ui.track_model import (
    KEYS,
    MIME,
    STRIP,
    TrackDelegate,
    TrackFilter,
    TrackModel,
    files_from_mime,
    ids_from_mime,
)

# Widths in base px (scaled with the text). FIXED columns keep theirs; the others share
# what's left of the pane in these proportions (never under MIN_FLEX)
WIDTHS = {"artist": 170, "title": 240, "album": 200, "genre": 120, "bpm": 62, "key": 50,
          "duration": 58, "rating": 92, "datetime_added": 92, "filetype": 48, "path": 300,
          "album_artist": 150, "composer": 140, "grouping": 110, "year": 52,
          "tracknumber": 40, "bitrate": 56, "comment": 200, "check": 96,
          "problem": 300}  # fmt: skip
FIXED = {"bpm", "key", "duration", "rating", "check", "datetime_added", "filetype", "year",
         "tracknumber", "bitrate"}  # fmt: skip
MIN_FLEX = 70
COMFY = 110  # a text column narrower than this on average: drop a low-priority column
DROP_ORDER = ["path", "filetype", "datetime_added", "key", "rating"]  # first to go


class TrackTable(QTableView):
    """A track table. Files dropped from Finder go to ``on_files``; with ``on_tracks`` set,
    tracks dragged in from another table go there (the crate pane)."""

    def __init__(self) -> None:
        super().__init__()
        self.on_files: Callable[[list[str]], None] | None = None
        self.on_tracks: Callable[[list[int]], None] | None = None
        self.on_hover: Callable[[bool], None] | None = None
        self.on_resize: Callable[[], None] | None = None
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        header.setStretchLastSection(False)  # the pane fits the columns itself
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setItemDelegate(TrackDelegate(self))
        self.restyle()

    def restyle(self) -> None:
        self.verticalHeader().setDefaultSectionSize(theme.row_height())
        self.horizontalHeader().setMinimumSectionSize(theme.px(STRIP))

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self.on_resize:
            self.on_resize()

    def _wanted(self, event: QDragMoveEvent | QDropEvent) -> str:
        mime = event.mimeData()
        if files_from_mime(mime) and self.on_files:
            return "files"
        if mime.hasFormat(MIME) and self.on_tracks and event.source() is not self:
            return "tracks"
        return ""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._wanted(event):
            event.acceptProposedAction()
            if self.on_hover:
                self.on_hover(True)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._wanted(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()  # tracks dragged within one table go nowhere

    def dragLeaveEvent(self, event: object) -> None:  # noqa: N802
        if self.on_hover:
            self.on_hover(False)
        super().dragLeaveEvent(event)  # type: ignore[arg-type]

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if self.on_hover:
            self.on_hover(False)
        kind = self._wanted(event)
        if not kind:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if kind == "files" and self.on_files:
            self.on_files(files_from_mime(event.mimeData()))
        elif kind == "tracks" and self.on_tracks:
            self.on_tracks(ids_from_mime(event.mimeData()))


class TrackPane(QFrame):
    def __init__(self, hidden_columns: set[str]) -> None:
        super().__init__()
        self.setObjectName("Pane")
        self.model = TrackModel()
        self.proxy = TrackFilter()
        self.proxy.setSourceModel(self.model)
        self.table = TrackTable()
        self.table.setModel(self.proxy)
        self.table.on_hover = self.set_drop_target
        self.table.on_resize = self.fit_columns
        self.auto_fit = True  # until a column is resized by hand
        self._fitting = False
        self.chosen_hidden = set(hidden_columns)  # the columns the person has turned off
        self.dropped: set[str] = set()  # turned off for now: the pane is too narrow
        self.forced: set[str] = set()  # shown in this view whatever was chosen (scan view)
        for key in hidden_columns:
            self.table.setColumnHidden(KEYS.index(key), True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(KEYS.index("color"), QHeaderView.ResizeMode.Fixed)
        header.sectionResized.connect(self._resized_by_hand)
        self.table.sortByColumn(KEYS.index("artist"), Qt.SortOrder.AscendingOrder)

        self.header = QWidget()
        self.header.setObjectName("PaneHeader")
        self.header_row = QHBoxLayout(self.header)

        self.empty = QWidget()
        col = QVBoxLayout(self.empty)
        col.addStretch()
        self.empty_title = QLabel()
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_text = QLabel()
        self.empty_text.setObjectName("EmptyText")
        self.empty_text.setWordWrap(True)
        for label in (self.empty_title, self.empty_text):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(label)
        self.empty_extra = QVBoxLayout()
        col.addLayout(self.empty_extra)
        col.addStretch()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)

        self.footer = QLabel()
        self.footer.setObjectName("Dim")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        self.bars = QVBoxLayout()  # extra rows under the header (the scan's controls)
        self.bars.setSpacing(0)
        layout.addLayout(self.bars)
        layout.addWidget(self.stack, 1)
        self.restyle()

    def restyle(self) -> None:
        m = theme.px(10)
        self.header_row.setContentsMargins(m, theme.px(6), m, theme.px(6))
        self.header_row.setSpacing(theme.px(6))
        self.header.setMinimumHeight(theme.px(40))
        self.empty_title.setFont(theme.font(16, bold=True))
        self.table.restyle()
        self.model.restyle()
        self.fit_columns()

    def _width(self, key: str) -> int:
        return theme.px(STRIP) + 2 if key == "color" else theme.px(WIDTHS[key])

    def fit_columns(self) -> None:
        """Fixed columns at their width; the text columns share the rest of the pane. When
        the pane is narrow, low-priority columns are left out until there's room again."""
        available = self.table.viewport().width()
        if available < 50:
            return
        chosen = [k for k in KEYS if k not in self.chosen_hidden or k in self.forced]
        dropped: set[str] = set()
        if self.auto_fit:
            for candidate in [None, *DROP_ORDER]:
                if candidate is not None:
                    if candidate not in chosen or candidate in self.forced:
                        continue
                    dropped.add(candidate)
                shown = [k for k in chosen if k not in dropped]
                flex = [k for k in shown if k != "color" and k not in FIXED]
                room = available - sum(self._width(k) for k in shown if k not in flex)
                if not flex or room >= len(flex) * theme.px(COMFY):
                    break
        self._fitting = True
        try:
            for i, k in enumerate(KEYS):
                self.table.setColumnHidden(i, k not in chosen or k in dropped)
            self.dropped = dropped
            if not self.auto_fit:
                return
            shown = [k for k in chosen if k not in dropped]
            flex = [k for k in shown if k != "color" and k not in FIXED]
            room = available - sum(self._width(k) for k in shown if k not in flex)
            widths = _share(room, {k: WIDTHS[k] for k in flex}, theme.px(MIN_FLEX))
            header = self.table.horizontalHeader()
            for k in shown:
                header.resizeSection(KEYS.index(k), widths.get(k) or self._width(k))
        finally:
            self._fitting = False

    def set_forced(self, keys: set[str]) -> None:
        if keys != self.forced:
            self.forced = keys
            self.fit_columns()

    def set_column_shown(self, key: str, on: bool) -> None:
        """The person turned a column on or off (the header's menu)."""
        if on:
            self.chosen_hidden.discard(key)
        else:
            self.chosen_hidden.add(key)
        self.fit_columns()

    def _resized_by_hand(self, *_args: object) -> None:
        if not self._fitting and self.table.isVisible():
            self.auto_fit = False

    def fit_again(self) -> None:
        self.auto_fit = True
        self.fit_columns()

    def set_drop_target(self, on: bool) -> None:
        self.setProperty("dropTarget", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_tracks(self, rows: list[Track], empty: tuple[str, str] | None = None) -> None:
        """Show these tracks; with ``empty`` and no rows, a message in their place."""
        self.model.set_tracks(rows)
        if empty and not rows:
            self.empty_title.setText(empty[0])
            self.empty_text.setText(empty[1])
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.table)

    def show_message(self, title: str, text: str) -> None:
        self.model.set_tracks([])
        self.empty_title.setText(title)
        self.empty_text.setText(text)
        self.stack.setCurrentWidget(self.empty)

    def selected_rows(self) -> list[int]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return sorted(rows)

    def selected_ids(self) -> list[int]:
        return [self.model.track(r).id for r in self.selected_rows()]

    def selected_tracks(self) -> list[Track]:
        return [self.model.track(r) for r in self.selected_rows()]

    def select_ids(self, ids: list[int]) -> None:
        want = set(ids)
        sel = self.table.selectionModel()
        for r, t in enumerate(self.model.rows):
            if t.id in want:
                idx = self.proxy.mapFromSource(self.model.index(r, 0))
                if idx.isValid():
                    sel.select(idx, sel.SelectionFlag.Select | sel.SelectionFlag.Rows)

    def save_state(self) -> QByteArray:
        return self.table.horizontalHeader().saveState()

    def restore_state(self, state: object, auto_fit: object = True,
                      hidden: object = None) -> None:  # fmt: skip
        """Columns as they were left: their order and which are shown; their widths too
        if they had been set by hand (else they're fitted to the pane)."""
        if isinstance(state, QByteArray) and not state.isEmpty():
            self._fitting = True
            try:
                self.table.horizontalHeader().restoreState(state)
            finally:
                self._fitting = False
        self.auto_fit = auto_fit not in (False, "false", 0, "0")
        if isinstance(hidden, (list, tuple)):
            self.chosen_hidden = {str(k) for k in hidden if str(k) in KEYS}
        elif isinstance(hidden, str) and hidden:
            self.chosen_hidden = {hidden} if hidden in KEYS else self.chosen_hidden
        self.fit_columns()


def _share(room: int, weights: dict[str, int], minimum: int) -> dict[str, int]:
    """Split ``room`` by weight; a column whose share is under ``minimum`` gets the minimum
    and the rest is split again among the others."""
    out: dict[str, int] = {}
    left = dict(weights)
    while left:
        total = sum(left.values()) or 1
        small = {k for k, w in left.items() if room * w / total < minimum}
        if not small:
            out.update({k: int(room * w / total) for k, w in left.items()})
            break
        for k in small:
            out[k] = minimum
            room -= minimum
            del left[k]
    return out
