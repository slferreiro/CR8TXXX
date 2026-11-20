# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Editing tracks' details: one track, or several at once (only the fields you change are
changed; a field whose tracks differ shows "(several values)")."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cr8txxx.db.tracks import Track

TEXT_FIELDS = [
    ("artist", "Artist"),
    ("title", "Title"),
    ("album", "Album"),
    ("album_artist", "Album Artist"),
    ("genre", "Genre"),
    ("composer", "Composer"),
    ("grouping", "Grouping"),
    ("year", "Year"),
    ("tracknumber", "Track #"),
    ("comment", "Comment"),
]
KEEP = "keep"
SEVERAL = "(several values)"


class EditDialog(QDialog):
    def __init__(self, tracks: list[Track], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tracks = tracks
        many = len(tracks) > 1
        self.setWindowTitle(f"Edit {len(tracks)} Tracks" if many else "Edit Track")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        if many:
            note = QLabel("Only the fields you change are changed on all the tracks.")
            note.setWordWrap(True)
            layout.addWidget(note)
        else:
            path = QLabel(tracks[0].path)
            path.setWordWrap(True)
            path.setStyleSheet("color: gray;")
            layout.addWidget(path)
        form = QFormLayout()
        layout.addLayout(form)

        self.edits: dict[str, QLineEdit] = {}
        self.touched: set[str] = set()
        for key, label in TEXT_FIELDS:
            values = {str(t.get(key) or "") for t in tracks}
            edit = QLineEdit()
            if len(values) == 1:
                edit.setText(values.pop())
            else:
                edit.setPlaceholderText(SEVERAL)
            edit.textEdited.connect(lambda _t, k=key: self.touched.add(k))
            form.addRow(label, edit)
            self.edits[key] = edit

        self.rating = QComboBox()
        self.rating.addItem("(unchanged)", KEEP)
        self.rating.addItem("No rating", 0)
        for n in range(1, 6):
            self.rating.addItem("★" * n, n)
        ratings = {int(t.get("rating") or 0) for t in tracks}  # type: ignore[call-overload]
        if len(ratings) == 1:
            self.rating.setCurrentIndex(self.rating.findData(ratings.pop()))
        self._rating_start = self.rating.currentData()
        form.addRow("Rating", self.rating)

        colors = {t.get("color") for t in tracks}
        self.color: object = colors.pop() if len(colors) == 1 else KEEP
        self._color_start = self.color
        row = QHBoxLayout()
        self.swatch = QPushButton()
        self.swatch.clicked.connect(self._pick_color)
        clear = QPushButton("No Color")
        clear.clicked.connect(lambda: self._set_color(None))
        row.addWidget(self.swatch)
        row.addWidget(clear)
        row.addStretch()
        holder = QWidget()
        holder.setLayout(row)
        form.addRow("Color", holder)
        self._show_color()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        note = QLabel("Changes are saved in Mixxx's library, not in the files' own tags.")
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)

    def _show_color(self) -> None:
        if self.color == KEEP:
            self.swatch.setText(SEVERAL)
            self.swatch.setStyleSheet("")
        elif self.color is None:
            self.swatch.setText("None — Choose…")
            self.swatch.setStyleSheet("")
        else:
            hexa = f"#{int(self.color) & 0xFFFFFF:06x}"  # type: ignore[call-overload]
            self.swatch.setText(f"{hexa} — Choose…")
            self.swatch.setStyleSheet(f"background: {hexa};")

    def _set_color(self, value: object) -> None:
        self.color = value
        self._show_color()

    def _pick_color(self) -> None:
        start = QColor(f"#{int(self.color) & 0xFFFFFF:06x}") if isinstance(self.color, int) \
            else QColor("white")  # fmt: skip
        picked = QColorDialog.getColor(start, self, "Track Color")
        if picked.isValid():
            self._set_color(int(picked.name()[1:], 16))

    def changes(self) -> dict[str, object]:
        """What to change: only the fields edited (and rating/color if set)."""
        out: dict[str, object] = {k: self.edits[k].text().strip() for k in self.touched}
        if self.rating.currentData() != self._rating_start and self.rating.currentData() != KEEP:
            out["rating"] = self.rating.currentData()
        if self.color != self._color_start and self.color != KEEP:
            out["color"] = self.color
        return out
