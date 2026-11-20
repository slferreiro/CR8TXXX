# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Mixxx crates: ``crates`` (one row per crate) and ``crate_tracks`` (which tracks are in
it). A locked crate can't be changed in Mixxx, and CR8TXXX refuses the same."""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cr8txxx.db import tracks
from cr8txxx.db.mixxx import Library


class CrateError(Exception):
    """A crate change that can't be made (the message says why)."""


@dataclass
class Crate:
    id: int
    name: str
    tracks: int
    show: bool
    locked: bool
    autodj: bool


def list_crates(lib: Library) -> list[Crate]:
    rows = lib.conn.execute(
        "SELECT c.id, c.name, COALESCE(c.show, 1), COALESCE(c.locked, 0),"
        " COALESCE(c.autodj_source, 0),"
        " (SELECT COUNT(*) FROM crate_tracks ct JOIN library l ON l.id = ct.track_id"
        "  WHERE ct.crate_id = c.id AND COALESCE(l.mixxx_deleted, 0) = 0)"
        " FROM crates c ORDER BY c.name COLLATE NOCASE"
    )
    return [Crate(r[0], r[1], r[5], bool(r[2]), bool(r[3]), bool(r[4])) for r in rows]


def get(lib: Library, crate_id: int) -> Crate:
    for c in list_crates(lib):
        if c.id == crate_id:
            return c
    raise CrateError("That crate no longer exists.")


def _unlocked(lib: Library, crate_id: int) -> Crate:
    crate = get(lib, crate_id)
    if crate.locked:
        raise CrateError(f"“{crate.name}” is locked. Unlock it first.")
    return crate


def _clean(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise CrateError("A crate needs a name.")
    return name


def create(lib: Library, name: str) -> int:
    name = _clean(name)
    try:
        with lib.write() as conn:
            return int(conn.execute("INSERT INTO crates (name) VALUES (?)", (name,)).lastrowid or 0)
    except sqlite3.IntegrityError as exc:
        raise CrateError(f"There is already a crate called “{name}”.") from exc


def find_or_create(lib: Library, name: str) -> int:
    row = lib.conn.execute("SELECT id FROM crates WHERE name = ?", (name,)).fetchone()
    return int(row[0]) if row else create(lib, name)


def rename(lib: Library, crate_id: int, name: str) -> None:
    _unlocked(lib, crate_id)
    name = _clean(name)
    try:
        with lib.write() as conn:
            conn.execute("UPDATE crates SET name = ? WHERE id = ?", (name, crate_id))
    except sqlite3.IntegrityError as exc:
        raise CrateError(f"There is already a crate called “{name}”.") from exc


def delete(lib: Library, crate_id: int) -> None:
    _unlocked(lib, crate_id)
    with lib.write() as conn:
        conn.execute("DELETE FROM crate_tracks WHERE crate_id = ?", (crate_id,))
        conn.execute("DELETE FROM crates WHERE id = ?", (crate_id,))


def set_locked(lib: Library, crate_id: int, locked: bool) -> None:
    with lib.write() as conn:
        conn.execute("UPDATE crates SET locked = ? WHERE id = ?", (int(locked), crate_id))


def set_show(lib: Library, crate_id: int, show: bool) -> None:
    with lib.write() as conn:
        conn.execute("UPDATE crates SET show = ? WHERE id = ?", (int(show), crate_id))


def set_autodj(lib: Library, crate_id: int, on: bool) -> None:
    with lib.write() as conn:
        conn.execute("UPDATE crates SET autodj_source = ? WHERE id = ?", (int(on), crate_id))


def add_tracks(lib: Library, crate_id: int, track_ids: list[int]) -> int:
    """Put tracks in a crate; how many were new to it."""
    _unlocked(lib, crate_id)
    with lib.write() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO crate_tracks (crate_id, track_id) VALUES (?, ?)",
            [(crate_id, t) for t in track_ids],
        )
        return conn.total_changes - before


def remove_tracks(lib: Library, crate_id: int, track_ids: list[int]) -> int:
    _unlocked(lib, crate_id)
    with lib.write() as conn:
        before = conn.total_changes
        conn.executemany(
            "DELETE FROM crate_tracks WHERE crate_id = ? AND track_id = ?",
            [(crate_id, t) for t in track_ids],
        )
        return conn.total_changes - before


# --- M3U ------------------------------------------------------------------------------------


def export_m3u(lib: Library, crate_id: int, dest: str) -> int:
    rows = tracks.in_crate(lib, crate_id)
    lines = ["#EXTM3U"]
    for t in rows:
        secs = int(float(t.get("duration") or 0))  # type: ignore[arg-type]
        lines.append(f"#EXTINF:{secs},{t.get('artist') or ''} - {t.get('title') or ''}")
        lines.append(t.path)
    Path(dest).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def read_m3u(src: str) -> list[str]:
    """The files an M3U/M3U8 lists (relative paths are taken from the playlist's folder)."""
    base = os.path.dirname(os.path.abspath(src))
    found = []
    for line in Path(src).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file://"):
            from urllib.parse import unquote, urlparse

            line = unquote(urlparse(line).path)
        found.append(os.path.normpath(os.path.join(base, line)))
    return found


def import_m3u(lib: Library, src: str, name: str) -> tuple[int, int, list[str]]:
    """A crate from an M3U: files not in the library are added first. Returns (crate id,
    tracks in it, files listed that don't exist)."""
    files = read_m3u(src)
    present = [f for f in files if os.path.exists(f)]
    gone = [f for f in files if not os.path.exists(f)]
    tracks.add_files(lib, present)
    ids = []
    for f in present:
        row = lib.conn.execute(
            "SELECT l.id FROM library l JOIN track_locations tl ON tl.id = l.location"
            " WHERE tl.location = ?",
            (os.path.abspath(f),),
        ).fetchone()
        if row:
            ids.append(int(row[0]))
    crate_id = create(lib, name)
    add_tracks(lib, crate_id, ids)
    return crate_id, len(ids), gone
