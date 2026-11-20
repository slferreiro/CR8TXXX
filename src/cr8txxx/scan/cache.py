# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The scan's results, kept in CR8TXXX's own file (never in Mixxx's database):
~/Library/Application Support/CR8TXXX/checks.sqlite, one row per file path. A file is
checked again only when its size or modified time changes (it was replaced), as in FMM.

A file found damaged stays marked (red in every view) until it leaves the library, or a
rescan finds a good file in its place, or it's marked "Verified Undamaged by Listening".
Those marks are kept apart (the ``verified`` table): Rescan Everything keeps them, and a mark
holds only while the file is unchanged (same size and modified time)."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cr8txxx import paths
from cr8txxx.scan.checker import VERSION

BAD = {"damaged", "unreadable"}  # red, and noted in Mixxx's Comment
WARN = {"suspect"}  # amber only


class Checks:
    """One connection to the results file (each thread opens its own)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.support_dir() / "checks.sqlite"
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS checks (path TEXT PRIMARY KEY, size INTEGER,"
            " mtime REAL, version INTEGER, status TEXT, result TEXT, checked TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS verified (path TEXT PRIMARY KEY, size INTEGER,"
            " mtime REAL, verified_at TEXT, was TEXT)"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def all(self) -> dict[str, dict[str, Any]]:
        """Every file's last result, by path; a file verified by listening (and unchanged
        since) is "verified", whatever the scan said."""
        found = {
            path: json.loads(result)
            for path, result in self.conn.execute("SELECT path, result FROM checks")
        }
        for path, row in self.verified().items():
            found[path] = {"status": "verified", "verified_at": row["verified_at"],
                           "was": row["was"]}  # fmt: skip
        return found

    # --- Verified Undamaged by Listening ------------------------------------------------------

    def verified(self) -> dict[str, dict[str, Any]]:
        """The marks that still hold (the file is the one that was listened to)."""
        out = {}
        rows = self.conn.execute("SELECT path, size, mtime, verified_at, was FROM verified")
        for path, size, mtime, at, was in rows.fetchall():
            if _same(path, size, mtime):
                out[path] = {"verified_at": at, "was": json.loads(was or "{}")}
        return out

    def is_verified(self, path: str) -> bool:
        row = self.conn.execute(
            "SELECT size, mtime FROM verified WHERE path = ?", (path,)
        ).fetchone()
        return bool(row) and _same(path, row[0], row[1])

    def verify(self, path: str, was: dict[str, Any]) -> None:
        """Listened to and fine: the file is never flagged again while it's unchanged."""
        stat = os.stat(path)
        self.conn.execute(
            "INSERT OR REPLACE INTO verified (path, size, mtime, verified_at, was)"
            " VALUES (?, ?, ?, ?, ?)",
            (path, stat.st_size, stat.st_mtime,
             datetime.now(UTC).isoformat(timespec="seconds"), json.dumps(was)),
        )  # fmt: skip
        self.conn.commit()

    def unverify(self, path: str) -> None:
        """Take the mark off; the file is checked again by the next scan."""
        self.conn.execute("DELETE FROM verified WHERE path = ?", (path,))
        self.conn.execute("DELETE FROM checks WHERE path = ?", (path,))
        self.conn.commit()

    def drop_stale_mark(self, path: str) -> None:
        """The file changed since it was verified: the mark no longer applies."""
        self.conn.execute("DELETE FROM verified WHERE path = ?", (path,))
        self.conn.commit()

    def statuses(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT path, status FROM checks"))

    def current(self, path: str, have_ffmpeg: bool) -> bool:
        """Whether the file's result still stands: same version, size and modified time
        (an "unchecked" one is checked again once ffmpeg is there)."""
        row = self.conn.execute(
            "SELECT size, mtime, version, status FROM checks WHERE path = ?", (path,)
        ).fetchone()
        if not row:
            return False
        size, mtime, version, status = row
        if version != VERSION or (status == "unchecked" and have_ffmpeg):
            return False
        try:
            stat = os.stat(path)
        except OSError:
            return status == "unreadable"
        return size == stat.st_size and mtime == stat.st_mtime

    def put(self, path: str, result: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO checks (path, size, mtime, version, status, result, checked)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (path, result.get("size"), result.get("mtime"), result.get("v"),
             result.get("status"), json.dumps(result), result.get("checked")),
        )  # fmt: skip
        self.conn.commit()

    def forget_all(self) -> None:
        """Everything is checked again (Rescan Everything). Verified marks are kept."""
        self.conn.execute("DELETE FROM checks")
        self.conn.commit()


def _same(path: str, size: object, mtime: object) -> bool:
    try:
        stat = os.stat(path)
    except OSError:
        return False
    return size == stat.st_size and mtime == stat.st_mtime
