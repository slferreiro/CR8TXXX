# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Tracks in the Mixxx library: listing, editing, adding, hiding/purging and relocating.

In Mixxx, ``library.location`` holds the id of the track's ``track_locations`` row, which
has the file's full path. Removing a track in Mixxx sets ``library.mixxx_deleted = 1``; the
row stays (with its cues and analysis) so re-adding the file brings them back.
"""

import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cr8txxx.db.mixxx import Library

AUDIO = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".opus", ".wv",
         ".mp4", ".alac", ".caf"}  # fmt: skip

# Shown in the table, in this order: (key, column in library or track_locations, heading)
COLUMNS = [
    ("artist", "artist", "Artist"),
    ("title", "title", "Title"),
    ("album", "album", "Album"),
    ("album_artist", "album_artist", "Album Artist"),
    ("genre", "genre", "Genre"),
    ("composer", "composer", "Composer"),
    ("grouping", "grouping", "Grouping"),
    ("year", "year", "Year"),
    ("tracknumber", "tracknumber", "#"),
    ("bpm", "bpm", "BPM"),
    ("key", "key", "Key"),
    ("duration", "duration", "Time"),
    ("bitrate", "bitrate", "kbps"),
    ("rating", "rating", "Rating"),
    ("comment", "comment", "Comment"),
    ("filetype", "filetype", "Type"),
    ("datetime_added", "datetime_added", "Added"),
    ("color", "color", "Color"),
]

# What the editor may change (text fields, plus rating and color)
EDITABLE = ["artist", "title", "album", "album_artist", "genre", "composer", "grouping",
            "year", "tracknumber", "comment", "rating", "color"]  # fmt: skip


@dataclass
class Track:
    id: int
    location_id: int | None
    path: str
    fs_deleted: bool
    filesize: int | None
    values: dict[str, object] = field(default_factory=dict)

    def get(self, key: str) -> object:
        return self.values.get(key)

    @property
    def missing(self) -> bool:
        return self.fs_deleted or not self.path


def _select(lib: Library) -> str:
    cols = []
    for key, col, _ in COLUMNS:
        cols.append(f"l.{col} AS {key}" if lib.has("library", col) else f"NULL AS {key}")
    return (
        "SELECT l.id AS id, l.location AS location_id, tl.location AS path, "
        "COALESCE(tl.fs_deleted, 0) AS fs_deleted, tl.filesize AS filesize, "
        + ", ".join(cols)
        + " FROM library l LEFT JOIN track_locations tl ON tl.id = l.location"
    )


def _track(row: object) -> Track:
    r = dict(row)  # type: ignore[call-overload]
    return Track(
        id=r["id"],
        location_id=r["location_id"],
        path=r["path"] or "",
        fs_deleted=bool(r["fs_deleted"]),
        filesize=r["filesize"],
        values={key: r[key] for key, _, _ in COLUMNS},
    )


def all_tracks(lib: Library) -> list[Track]:
    """Every track in the library (not the hidden/removed ones)."""
    sql = _select(lib) + " WHERE COALESCE(l.mixxx_deleted, 0) = 0 ORDER BY l.artist, l.title"
    return [_track(r) for r in lib.conn.execute(sql)]


def by_ids(lib: Library, ids: list[int]) -> list[Track]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [_track(r) for r in lib.conn.execute(_select(lib) + f" WHERE l.id IN ({marks})", ids)]


def in_crate(lib: Library, crate_id: int) -> list[Track]:
    sql = (
        _select(lib) + " JOIN crate_tracks ct ON ct.track_id = l.id WHERE ct.crate_id = ?"
        " AND COALESCE(l.mixxx_deleted, 0) = 0 ORDER BY l.artist, l.title"
    )
    return [_track(r) for r in lib.conn.execute(sql, (crate_id,))]


def missing(lib: Library) -> list[Track]:
    """Tracks whose file is gone: flagged by Mixxx, or not there now."""
    return [t for t in all_tracks(lib) if t.fs_deleted or not t.path or not os.path.exists(t.path)]


def roots(lib: Library) -> list[str]:
    """The music folders Mixxx watches (Preferences › Library)."""
    if "directories" not in lib.tables:
        return []
    return [r[0] for r in lib.conn.execute("SELECT directory FROM directories")]


def outside_roots(lib: Library, files: list[str]) -> list[str]:
    """Files not inside one of Mixxx's music folders. Sandboxed Mixxx can only open files in
    folders it was given, so these may not load in Mixxx."""
    tops = [os.path.join(os.path.normpath(r), "") for r in roots(lib)]
    return [f for f in files if not any(os.path.normpath(f).startswith(t) for t in tops)]


# --- Editing --------------------------------------------------------------------------------


def update_metadata(lib: Library, ids: list[int], changes: dict[str, object]) -> int:
    """Set these fields on these tracks (the database only, not the files' tags)."""
    fields = {k: v for k, v in changes.items() if k in EDITABLE and lib.has("library", k)}
    if not ids or not fields:
        return 0
    sets = ", ".join(f"{k} = ?" for k in fields)
    marks = ",".join("?" * len(ids))
    with lib.write() as conn:
        cur = conn.execute(
            f"UPDATE library SET {sets} WHERE id IN ({marks})", [*fields.values(), *ids]
        )
    return cur.rowcount


# --- Adding ---------------------------------------------------------------------------------


def audio_files(folder: str) -> list[str]:
    """Every music file in a folder and its subfolders."""
    found = []
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.startswith(".") and Path(name).suffix.lower() in AUDIO:
                found.append(os.path.join(top, name))
    return sorted(found)


def _tags(path: str) -> dict[str, object]:
    try:
        from tinytag import TinyTag

        tag = TinyTag.get(path)
    except Exception:  # noqa: BLE001 - any unreadable file still gets added, by name
        return {"title": Path(path).stem}
    return {
        "artist": tag.artist or "",
        "title": tag.title or Path(path).stem,
        "album": tag.album or "",
        "album_artist": tag.albumartist or "",
        "genre": tag.genre or "",
        "composer": tag.composer or "",
        "year": str(tag.year or "")[:4],
        "tracknumber": str(tag.track or ""),
        "comment": tag.comment or "",
        "duration": float(tag.duration or 0),
        "bitrate": int(tag.bitrate or 0),
        "samplerate": int(tag.samplerate or 0),
        "channels": int(tag.channels or 0),
    }


@dataclass
class AddResult:
    added: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)  # were removed; brought back
    already: list[str] = field(default_factory=list)


def add_files(lib: Library, files: list[str]) -> AddResult:
    """Add music files to the library. Tags come from the file; ``header_parsed = 0`` makes
    Mixxx read them again itself, and it analyses BPM/key when the track is first loaded."""
    result = AddResult()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    with lib.write() as conn:
        for path in files:
            path = os.path.abspath(path)
            loc = conn.execute(
                "SELECT id FROM track_locations WHERE location = ?", (path,)
            ).fetchone()
            if loc:
                row = conn.execute(
                    "SELECT id, mixxx_deleted FROM library WHERE location = ?", (loc[0],)
                ).fetchone()
                if row and row[1]:
                    conn.execute("UPDATE library SET mixxx_deleted = 0 WHERE id = ?", (row[0],))
                    conn.execute(
                        "UPDATE track_locations SET fs_deleted = 0 WHERE id = ?", (loc[0],)
                    )
                    result.restored.append(path)
                    continue
                if row:
                    result.already.append(path)
                    continue
                loc_id = loc[0]
            else:
                p = Path(path)
                loc_id = conn.execute(
                    "INSERT INTO track_locations (location, filename, directory, filesize,"
                    " fs_deleted, needs_verification) VALUES (?, ?, ?, ?, 0, 0)",
                    (path, p.name, str(p.parent), p.stat().st_size),
                ).lastrowid
            values = {
                **_tags(path),
                "location": loc_id,
                "filetype": Path(path).suffix.lower().lstrip("."),
                "datetime_added": now,
                "mixxx_deleted": 0,
                "header_parsed": 0,
            }
            values = {k: v for k, v in values.items() if lib.has("library", k)}
            cols = ", ".join(values)
            conn.execute(
                f"INSERT INTO library ({cols}) VALUES ({','.join('?' * len(values))})",
                list(values.values()),
            )
            result.added.append(path)
    return result


# --- Removing -------------------------------------------------------------------------------


def hide(lib: Library, ids: list[int]) -> int:
    """Remove from the library the way Mixxx does: hidden, with cues, analysis and crate
    entries kept, so adding the file again brings it all back (crates don't show hidden
    tracks)."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with lib.write() as conn:
        n = conn.execute(f"UPDATE library SET mixxx_deleted = 1 WHERE id IN ({marks})", ids)
    return n.rowcount


def hidden(lib: Library) -> list[Track]:
    """Tracks removed (hidden) from the library."""
    sql = _select(lib) + " WHERE COALESCE(l.mixxx_deleted, 0) = 1 ORDER BY l.artist, l.title"
    return [_track(r) for r in lib.conn.execute(sql)]


def unhide(lib: Library, ids: list[int]) -> int:
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with lib.write() as conn:
        n = conn.execute(f"UPDATE library SET mixxx_deleted = 0 WHERE id IN ({marks})", ids)
    return n.rowcount


def purge(lib: Library, ids: list[int]) -> int:
    """Forget the tracks entirely: their rows, cues, analysis, crate and playlist entries.
    The files on disk are never touched."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    with lib.write() as conn:
        locs = [r[0] for r in conn.execute(
            f"SELECT location FROM library WHERE id IN ({marks})", ids
        ) if r[0] is not None]  # fmt: skip
        for table in ("crate_tracks", "PlaylistTracks", "cues", "track_analysis"):
            if table in lib.tables:
                conn.execute(f"DELETE FROM {table} WHERE track_id IN ({marks})", ids)
        n = conn.execute(f"DELETE FROM library WHERE id IN ({marks})", ids).rowcount
        if locs:
            conn.execute(
                f"DELETE FROM track_locations WHERE id IN ({','.join('?' * len(locs))})", locs
            )
    return n


# --- Relocating -----------------------------------------------------------------------------


@dataclass
class Move:
    track_id: int
    location_id: int
    old: str
    new: str
    note: str = ""


def find_moves(lost: list[Track], folder: str) -> tuple[list[Move], list[Track]]:
    """Where missing tracks' files are now, by file name under ``folder`` (a file of the same
    size wins when several have the name). Returns the moves and the tracks not found."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for top, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            by_name[name.casefold()].append(os.path.join(top, name))
    moves, not_found = [], []
    for t in lost:
        if t.location_id is None or not t.path:
            not_found.append(t)
            continue
        options = by_name.get(os.path.basename(t.path).casefold(), [])
        if not options:
            not_found.append(t)
            continue
        note = ""
        if len(options) > 1:
            same = [p for p in options if t.filesize and _size(p) == t.filesize]
            options = same or options
            note = "same size" if same else f"{len(options)} files with this name; first taken"
        moves.append(Move(t.id, t.location_id, t.path, options[0], note))
    return moves, not_found


def _size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def apply_moves(lib: Library, moves: list[Move]) -> tuple[int, list[Move]]:
    """Point the tracks at their files' new places. A new place another track already has
    is skipped (returned), since Mixxx allows one track per file."""
    done, clashes = 0, []
    with lib.write() as conn:
        for m in moves:
            other = conn.execute(
                "SELECT id FROM track_locations WHERE location = ? AND id != ?",
                (m.new, m.location_id),
            ).fetchone()
            if other:
                clashes.append(m)
                continue
            p = Path(m.new)
            conn.execute(
                "UPDATE track_locations SET location = ?, filename = ?, directory = ?,"
                " filesize = ?, fs_deleted = 0, needs_verification = 0 WHERE id = ?",
                (m.new, p.name, str(p.parent), _size(m.new), m.location_id),
            )
            done += 1
    return done, clashes


# --- Damage notes (step 2) ------------------------------------------------------------------

DAMAGE_NOTE = "DAMAGED DO NOT USE - DELETE AND REPLACE THIS SONG"
_SEP = " | "


def noted(comment: object) -> bool:
    return str(comment or "").startswith(DAMAGE_NOTE)


def with_note(comment: object) -> str:
    """The comment with the damage note in front (once); what was there is kept after it."""
    text = str(comment or "")
    if noted(text):
        return text
    return DAMAGE_NOTE + (_SEP + text if text.strip() else "")


def without_note(comment: object) -> str:
    text = str(comment or "")
    if not noted(text):
        return text
    rest = text[len(DAMAGE_NOTE) :]
    return rest[len(_SEP) :] if rest.startswith(_SEP) else rest.lstrip()


def note_damage(lib: Library, damaged: list[int], fine: list[int]) -> tuple[int, int]:
    """Write the damage note into Mixxx's Comment of the damaged tracks, and take it out of
    tracks found fine again (their file was replaced). Returns (noted, cleared)."""
    if not lib.has("library", "comment"):
        return 0, 0
    want = set(damaged)
    ids = sorted(want | set(fine))
    if not ids:
        return 0, 0
    marks = ",".join("?" * len(ids))
    rows = lib.conn.execute(f"SELECT id, comment FROM library WHERE id IN ({marks})", ids)
    changes = []
    for track_id, comment in rows.fetchall():
        new = with_note(comment) if track_id in want else without_note(comment)
        if new != (comment or ""):
            changes.append((new, track_id))
    if not changes:
        return 0, 0
    with lib.write() as conn:
        conn.executemany("UPDATE library SET comment = ? WHERE id = ?", changes)
    added = sum(1 for _new, t in changes if t in want)
    return added, len(changes) - added


# --- Find New Songs -------------------------------------------------------------------------


def known_locations(lib: Library) -> set[str]:
    """Every file the library knows, hidden tracks' included (they stay hidden)."""
    return {r[0] for r in lib.conn.execute("SELECT location FROM track_locations") if r[0]}


def new_files(
    folders: list[str],
    known: set[str],
    progress: Callable[[str], object] | None = None,
    stop: Callable[[], bool] | None = None,
) -> tuple[list[str], list[str]]:
    """Music files in Mixxx's music folders that the library doesn't have yet, and the
    folders that couldn't be read (an unplugged drive). Safe to run off the main thread: it
    only reads the file system."""
    found: list[str] = []
    unreadable: list[str] = []
    for folder in folders:
        if not os.path.isdir(folder) or not os.access(folder, os.R_OK | os.X_OK):
            unreadable.append(folder)
            continue
        for top, dirs, files in os.walk(folder):
            if stop and stop():
                return sorted(found), unreadable
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if progress:
                progress(top)
            for name in files:
                if name.startswith(".") or Path(name).suffix.lower() not in AUDIO:
                    continue
                path = os.path.join(top, name)
                if path not in known and os.path.abspath(path) not in known:
                    found.append(path)
    return sorted(set(found)), unreadable
