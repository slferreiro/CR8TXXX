# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
import os
import sqlite3
from pathlib import Path

import pytest

from cr8txxx import paths
from cr8txxx.db import crates, tracks
from cr8txxx.db.mixxx import AccessDenied, Library, NotMixxxDB, ReadOnly


def test_opens_and_lists(lib: Library) -> None:
    assert lib.schema_version == 39
    assert lib.writable
    got = tracks.all_tracks(lib)
    assert [t.get("artist") for t in got] == ["Air", "Daft Punk", "Moby"]
    assert all(os.path.exists(t.path) for t in got)


def test_not_a_mixxx_db(tmp_path: Path) -> None:
    other = tmp_path / "x.sqlite"
    sqlite3.connect(other).execute("CREATE TABLE t (a)").connection.commit()
    with pytest.raises(NotMixxxDB):
        Library(other)
    (tmp_path / "y.sqlite").write_text("hello")
    with pytest.raises(NotMixxxDB):
        Library(tmp_path / "y.sqlite")


def test_access_denied(tmp_path: Path) -> None:
    from conftest import make_db

    db = make_db(tmp_path)
    db.chmod(0)
    try:
        with pytest.raises(AccessDenied):
            Library(db)
    finally:
        db.chmod(0o644)


def test_read_only_while_mixxx_runs(lib: Library, running: dict[str, bool]) -> None:
    running["mixxx"] = True
    assert "Quit Mixxx" in lib.why_read_only()
    with pytest.raises(ReadOnly):
        crates.create(lib, "New")
    running["mixxx"] = False
    crates.create(lib, "New")


def test_unknown_schema_is_read_only(lib: Library) -> None:
    lib.schema_version = 99
    with pytest.raises(ReadOnly):
        crates.create(lib, "New")


def test_first_write_backs_up(lib: Library) -> None:
    crates.create(lib, "A")
    crates.create(lib, "B")
    backups = list(paths.backups_dir().glob("mixxxdb-*.sqlite"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    assert copy.execute("SELECT name FROM crates").fetchall() == [("Warmup",)]


def test_failed_write_rolls_back(lib: Library) -> None:
    with pytest.raises(RuntimeError), lib.write() as conn:
        conn.execute("INSERT INTO crates (name) VALUES ('Half')")
        raise RuntimeError
    assert [c.name for c in crates.list_crates(lib)] == ["Warmup"]


def test_crates(lib: Library) -> None:
    (warm,) = crates.list_crates(lib)
    assert warm.tracks == 2
    new = crates.create(lib, "  Peak   Time ")
    assert crates.get(lib, new).name == "Peak Time"
    with pytest.raises(crates.CrateError):
        crates.create(lib, "Warmup")
    with pytest.raises(crates.CrateError):
        crates.create(lib, "   ")
    assert crates.add_tracks(lib, new, [1, 2, 3]) == 3
    assert crates.add_tracks(lib, new, [1]) == 0
    assert crates.remove_tracks(lib, new, [2]) == 1
    assert sorted(t.id for t in tracks.in_crate(lib, new)) == [1, 3]
    crates.rename(lib, new, "Peak")
    with pytest.raises(crates.CrateError):
        crates.rename(lib, new, "Warmup")
    crates.delete(lib, new)
    assert (
        lib.conn.execute("SELECT COUNT(*) FROM crate_tracks WHERE crate_id=?", (new,)).fetchone()[0]
        == 0
    )  # noqa: E501


def test_locked_crate_refuses_changes(lib: Library) -> None:
    crates.set_locked(lib, 1, True)
    for change in (
        lambda: crates.rename(lib, 1, "X"),
        lambda: crates.delete(lib, 1),
        lambda: crates.add_tracks(lib, 1, [3]),
        lambda: crates.remove_tracks(lib, 1, [1]),
    ):
        with pytest.raises(crates.CrateError):
            change()
    crates.set_locked(lib, 1, False)
    crates.add_tracks(lib, 1, [3])


def test_edit_metadata(lib: Library) -> None:
    n = tracks.update_metadata(lib, [1, 2], {"genre": "House", "rating": 4, "bpm": 1})
    assert n == 2
    got = {t.id: t for t in tracks.by_ids(lib, [1, 2])}
    assert got[1].get("genre") == "House" and got[2].get("rating") == 4
    assert got[1].get("bpm") == 121  # not editable: unchanged


def test_hide_unhide_purge(lib: Library) -> None:
    tracks.hide(lib, [1])
    assert 1 not in [t.id for t in tracks.all_tracks(lib)]
    assert [t.id for t in tracks.in_crate(lib, 1)] == [2]
    assert crates.list_crates(lib)[0].tracks == 1
    tracks.unhide(lib, [1])
    assert crates.list_crates(lib)[0].tracks == 2
    path = tracks.by_ids(lib, [1])[0].path
    tracks.purge(lib, [1])
    q = lib.conn.execute
    assert q("SELECT COUNT(*) FROM crate_tracks WHERE track_id=1").fetchone()[0] == 0
    assert q("SELECT COUNT(*) FROM cues WHERE track_id=1").fetchone()[0] == 0
    assert q("SELECT COUNT(*) FROM track_locations WHERE id=1").fetchone()[0] == 0
    assert os.path.exists(path)  # the file is never touched


def test_add_files(lib: Library, tmp_path: Path) -> None:
    music = tmp_path / "Music"
    new = music / "sub" / "New Song.mp3"
    new.parent.mkdir()
    new.write_bytes(b"\0" * 500)
    (music / "sub" / "cover.jpg").write_bytes(b"x")
    found = tracks.audio_files(str(music))
    assert str(new) in found and not any(f.endswith(".jpg") for f in found)
    result = tracks.add_files(lib, found)
    assert result.added == [str(new)] and len(result.already) == 3
    (added,) = [t for t in tracks.all_tracks(lib) if t.path == str(new)]
    assert added.get("title") == "New Song" and added.get("filetype") == "mp3"
    row = lib.conn.execute("SELECT header_parsed FROM library WHERE id=?", (added.id,)).fetchone()
    assert row[0] == 0
    # a hidden track comes back, keeping its crates
    tracks.hide(lib, [1])
    again = tracks.add_files(lib, [tracks.by_ids(lib, [1])[0].path])
    assert len(again.restored) == 1 and crates.list_crates(lib)[0].tracks == 2


def test_outside_roots(lib: Library, tmp_path: Path) -> None:
    inside = str(tmp_path / "Music" / "a.mp3")
    outside = str(tmp_path / "Elsewhere" / "b.mp3")
    assert tracks.outside_roots(lib, [inside, outside]) == [outside]


def test_relocate(lib: Library, tmp_path: Path) -> None:
    moved = tmp_path / "NewDrive" / "deep"
    moved.mkdir(parents=True)
    for t in tracks.all_tracks(lib)[:2]:
        os.rename(t.path, moved / os.path.basename(t.path))
    lost = tracks.missing(lib)
    assert len(lost) == 2
    moves, not_found = tracks.find_moves(lost, str(tmp_path / "NewDrive"))
    assert len(moves) == 2 and not not_found
    done, clashes = tracks.apply_moves(lib, moves)
    assert done == 2 and not clashes
    assert tracks.missing(lib) == []


def test_relocate_prefers_same_size(lib: Library, tmp_path: Path) -> None:
    t = tracks.by_ids(lib, [2])[0]
    name = os.path.basename(t.path)
    os.remove(t.path)
    for folder, size in (("a", 5), ("b", t.filesize)):
        (tmp_path / "X" / folder).mkdir(parents=True)
        (tmp_path / "X" / folder / name).write_bytes(b"\0" * (size or 0))
    moves, _ = tracks.find_moves(tracks.missing(lib), str(tmp_path / "X"))
    assert moves[0].new == str(tmp_path / "X" / "b" / name)


def test_m3u_round_trip(lib: Library, tmp_path: Path) -> None:
    m3u = tmp_path / "warm.m3u"
    assert crates.export_m3u(lib, 1, str(m3u)) == 2
    with m3u.open("a") as f:
        f.write("/nowhere/gone.mp3\n")
    crate_id, n, gone = crates.import_m3u(lib, str(m3u), "Warm copy")
    assert n == 2 and gone == ["/nowhere/gone.mp3"]
    assert crates.get(lib, crate_id).tracks == 2
