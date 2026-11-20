# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Verified Undamaged by Listening, and Find New Songs."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_db  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from test_scan import mp3, repeated, row_of, scan, with_break  # noqa: E402

from cr8txxx.db import tracks  # noqa: E402
from cr8txxx.db.mixxx import Library  # noqa: E402
from cr8txxx.scan import ffmpeg  # noqa: E402
from cr8txxx.scan.cache import Checks  # noqa: E402
from cr8txxx.ui import main_window as mw  # noqa: E402
from cr8txxx.ui.track_model import KEYS  # noqa: E402

OK = QMessageBox.StandardButton.Ok
CANCEL = QMessageBox.StandardButton.Cancel


@pytest.fixture
def answers() -> dict[str, object]:
    return {"question": QMessageBox.StandardButton.Yes, "confirm_new": True}


@pytest.fixture
def win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: dict[str, bool],
        answers: dict[str, object]):  # type: ignore[no-untyped-def]  # fmt: skip
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(Library.__init__, "__defaults__", (lambda: running["mixxx"],))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answers["question"])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(mw.MainWindow, "_confirm_new_songs",
                        lambda self, found, skipped: answers["confirm_new"])  # fmt: skip
    monkeypatch.setattr(ffmpeg, "locate", lambda folder="": None)
    monkeypatch.setattr(mw.MainWindow, "show_setup", lambda self: None)
    db = make_db(tmp_path)
    files = sorted((tmp_path / "Music").glob("*.mp3"))
    files[0].write_bytes(repeated(mp3(seed=1)))  # track 1: damaged
    files[1].write_bytes(mp3(seed=2))  # track 2: fine
    files[2].write_bytes(with_break(mp3(seed=3)))  # track 3: suspect
    w = mw.MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1400, 900)
    w.show()
    w.open_database(db)
    yield w
    w.close()


def status(w: mw.MainWindow, track_id: int) -> str:
    return w._status_of(tracks.by_ids(w.lib, [track_id])[0])


def comment(w: mw.MainWindow, track_id: int) -> str:
    return str(tracks.by_ids(w.lib, [track_id])[0].get("comment") or "")


# --- Verified Undamaged by Listening ---------------------------------------------------------


def test_verify_clears_red_and_note(win: mw.MainWindow, answers: dict[str, object]) -> None:
    tracks.update_metadata(win.lib, [1], {"comment": "big tune"})
    scan(win)
    assert comment(win, 1) == f"{tracks.DAMAGE_NOTE} | big tune"
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    assert status(win, 1) == "verified" and comment(win, 1) == "big tune"
    win.show_view(mw.ALL)
    m = win.library.model
    r = row_of(win.library, 1)
    assert m.data(m.index(r, 1), Qt.ItemDataRole.BackgroundRole) is None
    assert m.data(m.index(r, KEYS.index("check")), Qt.ItemDataRole.DisplayRole) == "Verified ✓"
    assert "verified undamaged by listening" in m.details[tracks.by_ids(win.lib, [1])[0].path]
    win.show_view(mw.SCAN)
    assert 1 not in [t.id for t in win.library.model.rows]
    assert "1 verified by listening" in win.scan_summary.text()


def test_cancel_changes_nothing(win: mw.MainWindow, answers: dict[str, object]) -> None:
    scan(win)
    answers["question"] = CANCEL
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    assert status(win, 1) == "damaged" and tracks.noted(comment(win, 1))


def test_hand_edited_comment_is_left_alone(win: mw.MainWindow, answers: dict[str, object]) -> None:
    scan(win)
    tracks.update_metadata(win.lib, [1], {"comment": "my own words"})
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    assert comment(win, 1) == "my own words"


def test_verified_survives_rescan_and_restart(win: mw.MainWindow, tmp_path: Path,
                                              answers: dict[str, object]) -> None:  # fmt: skip
    scan(win)
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1, 3]))
    answers["question"] = QMessageBox.StandardButton.Yes  # "Check all files again?"
    win.start_scan(rescan=True)  # Rescan Everything
    win.scan_worker.wait(20000)
    QApplication.processEvents()
    QApplication.processEvents()
    assert status(win, 1) == "verified" and status(win, 3) == "verified"
    assert not tracks.noted(comment(win, 1))
    win.close()
    again = mw.MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    again.open_database(tmp_path / "mixxxdb.sqlite")
    assert again._status_of(tracks.by_ids(again.lib, [1])[0]) == "verified"


def test_replaced_file_loses_the_mark(win: mw.MainWindow, answers: dict[str, object]) -> None:
    scan(win)
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    path = Path(tracks.by_ids(win.lib, [1])[0].path)
    path.write_bytes(repeated(mp3(seed=7)))  # a different (still damaged) file
    scan(win)
    assert status(win, 1) == "damaged" and tracks.noted(comment(win, 1))


def test_note_removal_waits_for_mixxx(win: mw.MainWindow, running: dict[str, bool],
                                      answers: dict[str, object]) -> None:  # fmt: skip
    scan(win)
    running["mixxx"] = True
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    assert status(win, 1) == "verified" and tracks.noted(comment(win, 1))
    assert win.notes_waiting == 1 and "damage note" in win.banner.text()
    running["mixxx"] = False
    win._check_guard()
    assert not tracks.noted(comment(win, 1)) and win.notes_waiting == 0


def test_remove_verified_mark_reflags(win: mw.MainWindow, answers: dict[str, object]) -> None:
    scan(win)
    answers["question"] = OK
    win.verify_tracks(tracks.by_ids(win.lib, [1]))
    win.unverify_tracks(tracks.by_ids(win.lib, [1]))
    win.scan_worker.wait(20000)
    QApplication.processEvents()
    QApplication.processEvents()
    assert status(win, 1) == "damaged" and tracks.noted(comment(win, 1))


def test_menu_offers_the_right_items(win: mw.MainWindow, answers: dict[str, object]) -> None:
    scan(win)
    flagged = [t for t in tracks.by_ids(win.lib, [1, 2, 3])
               if win._status_of(t) in mw.BAD | mw.WARN]  # fmt: skip
    assert sorted(t.id for t in flagged) == [1, 3]


def test_missing_file_cannot_be_verified(tmp_path: Path) -> None:
    cache = Checks(tmp_path / "c.sqlite")
    with pytest.raises(OSError):
        cache.verify(str(tmp_path / "gone.mp3"), {})
    assert cache.verified() == {}


# --- Find New Songs --------------------------------------------------------------------------


def find(win: mw.MainWindow) -> None:
    win.find_new_songs()
    assert win.folder_scan is not None
    win.folder_scan.wait(20000)
    QApplication.processEvents()
    QApplication.processEvents()


def test_new_files_found(lib: Library, tmp_path: Path) -> None:
    music = tmp_path / "Music"
    (music / "New Album").mkdir()
    new = music / "New Album" / "fresh.mp3"
    new.write_bytes(mp3())
    (music / "New Album" / "cover.jpg").write_bytes(b"x")
    (music / ".hidden.mp3").write_bytes(b"x")
    tracks.hide(lib, [2])  # hidden: its file is known, so not "new"
    found, unreadable = tracks.new_files(
        [*tracks.roots(lib), str(tmp_path / "Unplugged")], tracks.known_locations(lib)
    )
    assert found == [str(new)] and unreadable == [str(tmp_path / "Unplugged")]


def test_find_new_songs_adds_without_analysis(win: mw.MainWindow, tmp_path: Path,
                                              answers: dict[str, object]) -> None:  # fmt: skip
    new = tmp_path / "Music" / "fresh.mp3"
    new.write_bytes(mp3(seed=5))
    answers["question"] = QMessageBox.StandardButton.No  # don't scan for damage after
    find(win)
    (added,) = [t for t in tracks.all_tracks(win.lib) if t.path == str(new)]
    row = win.lib.conn.execute(
        "SELECT header_parsed, bpm, key FROM library WHERE id = ?", (added.id,)
    ).fetchone()
    assert row[0] == 0 and not row[1] and not row[2]
    assert win.library.model.rowCount() == 4


def test_find_new_songs_then_damage_check(win: mw.MainWindow, tmp_path: Path) -> None:
    new = tmp_path / "Music" / "broken.mp3"
    new.write_bytes(repeated(mp3(seed=6)))
    find(win)  # answers "Yes": check the new song now
    assert win.scan_worker is not None
    win.scan_worker.wait(20000)
    QApplication.processEvents()
    QApplication.processEvents()
    (added,) = [t for t in tracks.all_tracks(win.lib) if t.path == str(new)]
    assert win._status_of(added) == "damaged"


def test_find_new_songs_cancelled_adds_nothing(win: mw.MainWindow, tmp_path: Path,
                                               answers: dict[str, object]) -> None:  # fmt: skip
    (tmp_path / "Music" / "fresh.mp3").write_bytes(mp3(seed=5))
    answers["confirm_new"] = False
    find(win)
    assert len(tracks.all_tracks(win.lib)) == 3


def test_find_new_songs_read_only(win: mw.MainWindow, running: dict[str, bool]) -> None:
    running["mixxx"] = True
    win._check_guard()
    assert not win.a_find_new.isEnabled()
