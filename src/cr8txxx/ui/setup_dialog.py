# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""First-run setup ("Set Up CR8TXXX"): what this Mac needs, checked and put right with the
person's OK, one row each:

1. Mixxx's library: found, and readable (macOS's Full Disk Access).
2. ffmpeg, for checking files other than MP3: found, or downloaded into CR8TXXX's folder.

Shown on the first launch and from Help › Set Up CR8TXXX…; nothing here is required to
start (without ffmpeg the scan still checks MP3s)."""

import subprocess
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cr8txxx import paths
from cr8txxx.db.mixxx import AccessDenied, Library, NotMixxxDB, find_database
from cr8txxx.scan import ffmpeg, ffmpeg_download
from cr8txxx.ui import theme

READY, NEEDED, OPTIONAL = "ready", "needed", "optional"
DOWNLOAD_MB = 80  # about: ffmpeg + ffprobe, zipped


class Download(QThread):
    progress = Signal(str, int)  # name, bytes so far
    done = Signal(object, str)  # the Tool (or None), what went wrong

    def __init__(self, urls: dict[str, str] | None = None) -> None:
        super().__init__()
        self.urls = urls
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            tool = ffmpeg_download.install(self.urls, self.progress.emit, lambda: self._stop)
        except (ffmpeg_download.DownloadError, OSError) as exc:
            self.done.emit(None, str(exc))
            return
        self.done.emit(tool, "")


class SetupDialog(QDialog):
    database_chosen = Signal(str)  # a library file the person picked

    def __init__(self, remembered: str = "", parent: QWidget | None = None,
                 urls: dict[str, str] | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle("Set Up CR8TXXX")
        self.remembered = remembered
        self.urls = urls
        self.download: Download | None = None
        theme.fit_to_screen(self, 0.42, 0.5, 620, 420)

        col = QVBoxLayout(self)
        col.setSpacing(theme.px(14))
        head = QLabel(
            f'<span style="font-size:{theme.px(20)}px; font-weight:700;">'
            f'<span style="color:{theme.BRIGHT};">CR8T</span>'
            f'<span style="color:{theme.BLUE};">XXX</span></span>'
            f'<br><span style="color:{theme.DIM2};">Let\'s check what this Mac needs. Each step '
            "asks before it changes anything.</span>"
        )
        col.addWidget(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(theme.px(12))
        self.grid.setVerticalSpacing(theme.px(16))
        col.addLayout(self.grid)
        self.rows: dict[str, tuple[QLabel, QLabel, QLabel, QHBoxLayout]] = {}
        for i, (key, title) in enumerate(
            (("library", "Mixxx library"), ("ffmpeg", "ffmpeg (checks files other than MP3)"))
        ):
            mark, name, detail = QLabel(), QLabel(title), QLabel()
            name.setFont(theme.font(14, bold=True))
            detail.setWordWrap(True)
            detail.setObjectName("EmptyText")
            buttons = QHBoxLayout()
            text = QVBoxLayout()
            text.addWidget(name)
            text.addWidget(detail)
            text.addLayout(buttons)
            self.grid.addWidget(mark, i, 0)
            self.grid.addLayout(text, i, 1)
            self.rows[key] = (mark, name, detail, buttons)
        self.bar = QProgressBar()
        self.bar.hide()
        col.addWidget(self.bar)
        col.addStretch()
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        col.addWidget(line)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.go = QPushButton("Start Using CR8TXXX")
        self.go.setObjectName("Primary")
        self.go.setDefault(True)
        self.go.clicked.connect(self.accept)
        bottom.addWidget(self.go)
        col.addLayout(bottom)
        self.refresh()

    # --- The rows ------------------------------------------------------------------------------

    def _set(self, key: str, state: str, detail: str,
             actions: list[tuple[str, Callable[[], None]]]) -> None:  # fmt: skip
        mark, _name, label, buttons = self.rows[key]
        color, glyph = {READY: (theme.GREEN, "✓"), NEEDED: (theme.ORANGE, "!"),
                        OPTIONAL: (theme.AMBER, "–")}[state]  # fmt: skip
        mark.setText(f'<span style="color:{color}; font-size:{theme.px(22)}px; '
                     f'font-weight:700;">{glyph}</span>')  # fmt: skip
        label.setText(detail)
        while buttons.count():
            item = buttons.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for text, slot in actions:
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()

    def refresh(self) -> None:
        self.library_state = self._check_library()
        self.ffmpeg_state = self._check_ffmpeg()

    def _check_library(self) -> str:
        path = find_database(self.remembered)
        if path is None:
            self._set(
                "library",
                NEEDED,
                "No Mixxx library on this Mac yet. Open Mixxx once and add your music "
                "folder (Mixxx › Preferences › Library), then check again.",
                [("Check Again", self.refresh), ("Choose Library File…", self._choose)],
            )
            return NEEDED
        try:
            Library(path).close()
        except AccessDenied:
            self._set("library", NEEDED,
                      "macOS needs your permission for CR8TXXX to read Mixxx's library. Open "
                      "Full Disk Access, turn on CR8TXXX (add it with + if it isn't listed), "
                      "then quit and reopen CR8TXXX.",
                      [("Open Full Disk Access", self._open_privacy),
                       ("Choose Library File…", self._choose)])  # fmt: skip
            return NEEDED
        except NotMixxxDB as exc:
            self._set("library", NEEDED, str(exc), [("Choose Library File…", self._choose)])
            return NEEDED
        self._set("library", READY, f"Found and readable:\n{path}", [])
        return READY

    def _check_ffmpeg(self) -> str:
        ffmpeg.forget()
        tool = ffmpeg.locate()
        if tool:
            where = "inside CR8TXXX" if "_MEI" in tool.ffmpeg or ".app/" in tool.ffmpeg else (
                tool.ffmpeg.rsplit("/", 1)[0])  # fmt: skip
            self._set("ffmpeg", READY, f"ffmpeg {tool.version} is ready ({where}).", [])
            return READY
        self._set("ffmpeg", OPTIONAL,
                  "Not on this Mac. Without it the damaged-file scan checks MP3s only. "
                  f"Download and install it into CR8TXXX's own folder (about {DOWNLOAD_MB} MB, "
                  "no password needed)?",
                  [("Download && Install", self.start_download)])  # fmt: skip
        return OPTIONAL

    # --- Actions -------------------------------------------------------------------------------

    def _open_privacy(self) -> None:
        subprocess.run(["/usr/bin/open", paths.FULL_DISK_ACCESS_PANE], check=False)

    def _choose(self) -> None:
        start = str(paths.SANDBOXED if paths.SANDBOXED.exists() else paths.HOME)
        name, _ = QFileDialog.getOpenFileName(
            self, "Choose Mixxx Library", start, "Mixxx library (mixxxdb.sqlite *.sqlite)"
        )
        if name:
            self.remembered = name
            self.database_chosen.emit(name)
            self.refresh()

    def start_download(self) -> None:
        if self.download:
            return
        self._set("ffmpeg", OPTIONAL, "Downloading ffmpeg…", [("Cancel", self.cancel_download)])
        self.bar.setRange(0, DOWNLOAD_MB)
        self.bar.setValue(0)
        self.bar.show()
        self.go.setEnabled(False)
        self.download = Download(self.urls)
        self.download.progress.connect(self._progress)
        self.download.done.connect(self._downloaded)
        self.download.start()

    def cancel_download(self) -> None:
        if self.download:
            self.download.cancel()

    def _progress(self, name: str, size: int) -> None:
        mb = size / 1_000_000
        self.bar.setMaximum(max(self.bar.maximum(), int(mb) + 1))
        self.bar.setValue(int(mb))
        self.bar.setFormat(f"{name}: {mb:.0f} MB")

    def _downloaded(self, tool: object, error: str) -> None:
        job, self.download = self.download, None
        if job:
            job.wait()
        self.bar.hide()
        self.go.setEnabled(True)
        if error:
            why = (
                f"{error}\nThe scan still checks MP3s without it. Or install ffmpeg with "
                "Homebrew (brew.sh): brew install ffmpeg"
            )
            self._set("ffmpeg", OPTIONAL, why, [("Try Again", self.start_download)])
            return
        self.refresh()

    def reject(self) -> None:  # Esc / closing the window
        self.cancel_download()
        if self.download:
            self.download.wait(5000)
        super().reject()
