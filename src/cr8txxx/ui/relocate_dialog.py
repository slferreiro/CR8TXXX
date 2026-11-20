# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Finding missing tracks' files again: choose a folder, see where each was found, and
confirm. Nothing changes until Apply."""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cr8txxx.db import tracks
from cr8txxx.db.tracks import Move, Track
from cr8txxx.ui import theme


class RelocateDialog(QDialog):
    def __init__(self, lost: list[Track], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lost = lost
        self.moves: list[Move] = []
        self.setWindowTitle("Relocate Missing Files")
        self.setAcceptDrops(True)
        theme.fit_to_screen(self, 0.6, 0.6, 760, 440)
        layout = QVBoxLayout(self)
        self.info = QLabel(
            f"{len(lost):,} tracks' files are missing. Choose a folder (a drive, or where "
            "the music was moved to), or drag one here from Finder, and CR8TXXX looks inside it "
            "for files with the same names."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        row = QHBoxLayout()
        choose = QPushButton("Choose Folder…")
        choose.clicked.connect(self._choose)
        row.addWidget(choose)
        row.addStretch()
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Was", "Found at", "Note"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Where are the files now?")
        if folder:
            self.search(folder)

    def _dropped_folder(self, event: QDragEnterEvent | QDropEvent) -> str:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        folders = [
            u.toLocalFile() for u in urls if u.isLocalFile() and os.path.isdir(u.toLocalFile())
        ]
        return folders[0] if folders else ""

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._dropped_folder(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        folder = self._dropped_folder(event)
        if folder:
            event.acceptProposedAction()
            self.search(folder)

    def search(self, folder: str) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            moves, not_found = tracks.find_moves(self.lost, folder)
        finally:
            QApplication.restoreOverrideCursor()
        self.moves = moves
        self.table.setRowCount(len(moves))
        for r, m in enumerate(moves):
            was = QTableWidgetItem(m.old)
            was.setFlags(was.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            was.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(r, 0, was)
            self.table.setItem(r, 1, QTableWidgetItem(m.new))
            self.table.setItem(r, 2, QTableWidgetItem(m.note))
        self.info.setText(
            f"Found {len(moves):,} of {len(self.lost):,} in {folder}. "
            f"{len(not_found):,} not found. Untick any you don't want, then Apply."
        )
        self.apply.setEnabled(bool(moves))

    def chosen(self) -> list[Move]:
        return [
            m for r, m in enumerate(self.moves)
            if (item := self.table.item(r, 0)) and item.checkState() == Qt.CheckState.Checked
        ]  # fmt: skip
