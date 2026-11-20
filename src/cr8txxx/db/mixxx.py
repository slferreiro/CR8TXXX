# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The Mixxx library database (mixxxdb.sqlite): opening it, and writing to it safely.

The schema is Mixxx's, so this is plain sqlite3 that only touches the tables and columns
CR8TXXX needs, and checks which optional columns exist.

Safety rules:
- No writes while Mixxx is running. Mixxx keeps the library in memory and would overwrite
  (or be confused by) changes made underneath it.
- The first write of each session makes a timestamped backup copy of the database first.
- Each user action is one transaction: it all happens, or none of it does.
"""

import shutil
import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from cr8txxx import paths

# Schema versions this code knows (Mixxx 2.3 is 36, 2.4 is 39, 2.5 is 39/40). Anything
# else opens read-only, so an unknown future layout is never written to.
KNOWN_SCHEMAS = range(33, 45)
KEEP_BACKUPS = 10


class AccessDenied(Exception):
    """macOS won't let CR8TXXX read the file (Full Disk Access isn't granted)."""


class NotMixxxDB(Exception):
    """The file isn't a Mixxx library database."""


class ReadOnly(Exception):
    """A write was asked for while writing isn't allowed (the message says why)."""


def mixxx_running() -> bool:
    """Whether Mixxx is open on this Mac."""
    try:
        done = subprocess.run(
            ["/usr/bin/pgrep", "-xi", "mixxx"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def find_database(remembered: str = "") -> Path | None:
    """The first Mixxx database that exists: the one chosen before, else Mixxx's places.
    A file macOS hides from us still counts as existing (it's then AccessDenied on open)."""
    tries = ([Path(remembered)] if remembered else []) + paths.candidates()
    for path in tries:
        try:
            if path.is_file():
                return path
        except PermissionError:
            return path
        # In a container we may not list: is_file() says False, so look at the folder
        if not path.parent.exists():
            continue
        try:
            list(path.parent.iterdir())
        except PermissionError:
            return path
    return None


class Library:
    """An open Mixxx database."""

    def __init__(self, path: Path, running: Callable[[], bool] = mixxx_running) -> None:
        self.path = Path(path)
        self._running = running
        self._backed_up = False
        try:
            with open(self.path, "rb") as f:
                head = f.read(16)
        except PermissionError as exc:
            raise AccessDenied(str(self.path)) from exc
        except FileNotFoundError as exc:
            raise NotMixxxDB(f"{self.path} doesn't exist") from exc
        if head != b"SQLite format 3\x00":
            raise NotMixxxDB(f"{self.path} isn't an SQLite database")
        try:
            self.conn = sqlite3.connect(str(self.path), timeout=5)
        except sqlite3.OperationalError as exc:
            raise AccessDenied(str(exc)) from exc
        self.conn.row_factory = sqlite3.Row
        tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master")}
        if not {"library", "track_locations", "crates", "crate_tracks"} <= tables:
            self.conn.close()
            raise NotMixxxDB(f"{self.path} isn't a Mixxx library (no library/crates tables)")
        self.tables = tables
        self.columns = {t: self._columns(t) for t in ("library", "track_locations", "crates")}
        self.schema_version = self._schema_version()

    def _columns(self, table: str) -> set[str]:
        return {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _schema_version(self) -> int | None:
        if "settings" not in self.tables:
            return None
        row = self.conn.execute(
            "SELECT value FROM settings WHERE name = 'mixxx.schema.version'"
        ).fetchone()
        try:
            return int(row[0]) if row else None
        except (TypeError, ValueError):
            return None

    def close(self) -> None:
        self.conn.close()

    # --- Whether writing is allowed ---------------------------------------------------------

    def why_read_only(self) -> str:
        """ "" when writing is allowed, else why not (for the banner)."""
        if self.schema_version is not None and self.schema_version not in KNOWN_SCHEMAS:
            return (
                f"This database's schema (version {self.schema_version}) is newer or older "
                "than CR8TXXX knows, so it is opened read-only."
            )
        if self._running():
            return "Mixxx is running. Quit Mixxx to make changes (browsing still works)."
        return ""

    @property
    def writable(self) -> bool:
        return not self.why_read_only()

    def backup(self) -> Path:
        """A consistent copy of the database (SQLite's own backup), keeping the last 10."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = paths.backups_dir() / f"mixxxdb-{stamp}.sqlite"
        target = sqlite3.connect(str(dest))
        with target:
            self.conn.backup(target)
        target.close()
        old = sorted(paths.backups_dir().glob("mixxxdb-*.sqlite"))[:-KEEP_BACKUPS]
        for path in old:
            path.unlink(missing_ok=True)
        return dest

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One change to the library: refused when read-only, backed up the first time."""
        why = self.why_read_only()
        if why:
            raise ReadOnly(why)
        if not self._backed_up:
            self.backup()
            self._backed_up = True
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            yield self.conn
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def has(self, table: str, column: str) -> bool:
        return column in self.columns.get(table, set())


def copy_for_testing(source: Path, dest: Path) -> Path:
    """A copy of a database to try things on (make testdb)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return dest
