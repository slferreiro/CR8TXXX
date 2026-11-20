# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Help › About CR8TXXX: the version, the GPL notice, and the third-party licences."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cr8txxx import SOURCE_URL, __version__
from cr8txxx.ui import theme


def resources() -> Path:
    """Where LICENSE, THIRD_PARTY_NOTICES.md and licenses/ are: inside the app, or the
    project folder when run from source."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parents[3]


NOTICE = (
    "CR8TXXX is free software: you can redistribute it and/or modify it under the terms of "
    "the GNU General Public License as published by the Free Software Foundation, either "
    "version 3 of the License, or (at your option) any later version.<br><br>"
    "It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without "
    "even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See "
    "the GNU General Public License for more details."
)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About CR8TXXX")
        col = QVBoxLayout(self)
        source = f'<br>Source code: <a href="{SOURCE_URL}">{SOURCE_URL}</a>' if SOURCE_URL else ""
        head = QLabel(
            f'<span style="font-size:{theme.px(24)}px; font-weight:700;">'
            f'<span style="color:{theme.BRIGHT};">CR8T</span>'
            f'<span style="color:{theme.BLUE};">XXX</span></span>'
            f'<br><span style="color:{theme.DIM2};">Version {__version__} · '
            f"Manage your Mixxx library and crates, and find damaged music files.</span>"
            f"<br><br>Copyright © 2026 Sean Ferreiro{source}<br><br>{NOTICE}"
        )
        head.setWordWrap(True)
        head.setOpenExternalLinks(True)
        col.addWidget(head)
        self.notices = QTextBrowser()
        self.notices.setOpenExternalLinks(True)
        path = resources() / "THIRD_PARTY_NOTICES.md"
        self.notices.setMarkdown(path.read_text(encoding="utf-8") if path.exists() else
                                 "THIRD_PARTY_NOTICES.md is missing.")  # fmt: skip
        col.addWidget(self.notices, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        texts = QPushButton("Show Licence Texts")
        texts.clicked.connect(self.show_texts)
        buttons.addButton(texts, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        theme.fit_to_screen(self, 0.45, 0.65, 640, 520)

    def show_texts(self) -> None:
        subprocess.run(["/usr/bin/open", str(resources() / "licenses")], check=False)
