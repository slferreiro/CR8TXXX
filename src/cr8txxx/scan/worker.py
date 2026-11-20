# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The scan, in the background: every library file whose result is missing or out of date
is checked, a file at a time, with progress and a Cancel."""

import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from cr8txxx.scan import checker, ffmpeg
from cr8txxx.scan.cache import Checks

GIVE_WAY = 0.01  # seconds after each file, so the window stays quick (FMM's GIVE_WAY)


class ScanWorker(QThread):
    progress = Signal(int, int, str)  # done, total, the file now
    checked = Signal(str, str)  # path, status
    done = Signal(dict)  # counts: checked, skipped, cancelled, ffmpeg

    def __init__(self, files: list[str], rescan: bool = False,
                 cache_path: Path | None = None) -> None:  # fmt: skip
        super().__init__()
        self.files = files
        self.rescan = rescan
        self.cache_path = cache_path
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        tool = ffmpeg.locate()
        checks = Checks(self.cache_path)  # this thread's own connection
        counts = {"checked": 0, "skipped": 0, "cancelled": False, "ffmpeg": tool is not None}
        try:
            if self.rescan:
                checks.forget_all()
            total = len(self.files)
            for n, path in enumerate(self.files):
                if self._stop:
                    counts["cancelled"] = True
                    break
                self.progress.emit(n, total, path)
                if checks.is_verified(path):  # listened to and fine: never flagged again
                    counts["skipped"] += 1
                    continue
                checks.drop_stale_mark(path)  # replaced since it was verified (if it was)
                if checks.current(path, tool is not None):
                    counts["skipped"] += 1
                    continue
                result = checker.check_file(path, tool)
                checks.put(path, result)
                counts["checked"] += 1
                self.checked.emit(path, str(result.get("status")))
                time.sleep(GIVE_WAY)
            else:
                self.progress.emit(total, total, "")
        finally:
            checks.close()
            self.done.emit(counts)


class FolderScan(QThread):
    """Mixxx's music folders, walked for songs not in the library yet (Find New Songs)."""

    progress = Signal(str)  # the folder now
    done = Signal(list, list, bool)  # new files, folders that couldn't be read, cancelled

    def __init__(self, roots: list[str], known: set[str]) -> None:
        super().__init__()
        self.roots = roots
        self.known = known
        self._stop = False

    def cancel(self) -> None:
        self._stop = True

    def run(self) -> None:
        from cr8txxx.db.tracks import new_files

        found, unreadable = new_files(self.roots, self.known, self.progress.emit,
                                      lambda: self._stop)  # fmt: skip
        self.done.emit(found, unreadable, self._stop)
