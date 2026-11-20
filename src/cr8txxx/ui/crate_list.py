# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The crate list (top right): every crate with its track count, lock and Auto DJ marks.
Tracks dragged onto a crate are added to it; files from Finder are added to the library and
to that crate."""

from PySide6.QtCore import QModelIndex, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from cr8txxx.db.crates import Crate
from cr8txxx.ui import icons, theme
from cr8txxx.ui.track_model import MIME, files_from_mime, ids_from_mime

ROLE = Qt.ItemDataRole.UserRole


class CrateDelegate(QStyledItemDelegate):
    def __init__(self, owner: "CrateList") -> None:
        super().__init__(owner)
        self.owner = owner

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(100, round(theme.row_height() * 1.15))

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        crate: Crate = index.data(ROLE)
        r = QRectF(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        target = self.owner.drop_row == index.row()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = theme.ACTIVE if target else theme.CRATE_SELECT if selected else (
            theme.PANEL2 if hover else None)  # fmt: skip
        if bg:
            p.fillRect(r, QColor(bg))
        if selected:
            p.fillRect(QRectF(r.left(), r.top(), theme.px(3), r.height()), QColor(theme.ORANGE))
        if target:
            p.setPen(QPen(QColor(theme.BLUE), 1, Qt.PenStyle.DashLine))
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))

        pad = theme.px(12)
        size = theme.px(15)
        x = r.left() + pad
        cy = r.center().y()
        color = theme.ORANGE if selected else theme.DIM
        icons.icon("crate", color).paint(p, round(x), round(cy - size / 2), size, size)
        x += size + theme.px(8)

        font = theme.font()
        small = theme.font(10, bold=True)
        fm, sfm = QFontMetrics(font), QFontMetrics(small)
        right = r.right() - pad
        count = f"{crate.tracks:,}"
        p.setFont(theme.numeric_font(font))
        p.setPen(QColor(theme.DIM2))
        cw = fm.horizontalAdvance(count)
        p.drawText(QRectF(right - cw, r.top(), cw, r.height()), Qt.AlignmentFlag.AlignVCenter,
                   count)  # fmt: skip
        right -= cw + theme.px(10)
        if crate.autodj:
            text = "AUTO DJ"
            w = sfm.horizontalAdvance(text) + theme.px(8)
            box = QRectF(right - w, cy - sfm.height() / 2 - 1, w, sfm.height() + 2)
            p.setPen(QPen(QColor(theme.GREEN), 1))
            p.drawRoundedRect(box, 3, 3)
            p.setFont(small)
            p.setPen(QColor(theme.GREEN))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            right -= w + theme.px(8)
        if crate.locked:
            ls = theme.px(13)
            icons.icon("lock", theme.DIM2).paint(p, round(right - ls), round(cy - ls / 2), ls, ls)
            right -= ls + theme.px(8)

        p.setFont(font)
        p.setPen(QColor("#ffffff" if selected else theme.TEXT if crate.show else theme.DIM))
        name = fm.elidedText(crate.name, Qt.TextElideMode.ElideRight, int(right - x))
        p.drawText(QRectF(x, r.top(), right - x, r.height()), Qt.AlignmentFlag.AlignVCenter, name)
        p.restore()


class CrateList(QListWidget):
    crate_chosen = Signal(int)  # crate id (0: none)
    tracks_dropped = Signal(int, list)  # crate id, track ids
    files_dropped = Signal(int, list)  # crate id (0: just the library), files/folders
    menu_asked = Signal(int, QPoint)  # crate id (0: the empty area), global position

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Crates")
        self.drop_row = -1
        self.setItemDelegate(CrateDelegate(self))
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.currentItemChanged.connect(self._chosen)

    def set_crates(self, crates: list[Crate]) -> None:
        current = self.current_id()
        self.blockSignals(True)
        self.clear()
        for c in crates:
            item = QListWidgetItem(c.name)
            item.setData(ROLE, c)
            tips = [c.name, "Locked" if c.locked else "", "Auto DJ source" if c.autodj else "",
                    "" if c.show else "Hidden in Mixxx's sidebar"]  # fmt: skip
            item.setToolTip("\n".join(t for t in tips if t))
            self.addItem(item)
            if c.id == current:
                self.setCurrentItem(item)
        self.blockSignals(False)
        if current and self.current_id() != current:
            self.crate_chosen.emit(0)  # the crate shown was deleted

    def select(self, crate_id: int) -> None:
        for i in range(self.count()):
            item = self.item(i)
            if item.data(ROLE).id == crate_id:
                self.setCurrentItem(item)
                return

    def current_id(self) -> int:
        item = self.currentItem()
        return item.data(ROLE).id if item else 0

    def _chosen(self, item: QListWidgetItem | None, _old: object) -> None:
        self.crate_chosen.emit(item.data(ROLE).id if item else 0)

    def _menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        self.menu_asked.emit(item.data(ROLE).id if item else 0, self.viewport().mapToGlobal(pos))

    # --- Drag and drop ----------------------------------------------------------------------

    def _crate_at(self, pos: QPoint) -> tuple[int, int]:
        item = self.itemAt(pos)
        return (self.row(item), item.data(ROLE).id) if item else (-1, 0)

    def _set_target(self, row: int) -> None:
        if row != self.drop_row:
            self.drop_row = row
            self.viewport().update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasFormat(MIME) or files_from_mime(mime):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        row, crate_id = self._crate_at(event.position().toPoint())
        mime = event.mimeData()
        ok = bool(crate_id) or bool(files_from_mime(mime))  # files: onto a crate, or the list
        self._set_target(row if crate_id else -1)
        if ok:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: object) -> None:  # noqa: N802
        self._set_target(-1)
        super().dragLeaveEvent(event)  # type: ignore[arg-type]

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_target(-1)
        _row, crate_id = self._crate_at(event.position().toPoint())
        mime = event.mimeData()
        ids, files = ids_from_mime(mime), files_from_mime(mime)
        if crate_id and ids:
            self.tracks_dropped.emit(crate_id, ids)
        elif files:
            self.files_dropped.emit(crate_id, files)
        else:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
