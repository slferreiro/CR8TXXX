# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Step 2: the damaged file scan. FMM's checker on real MP3 frames (good, with a repeated
block, with a break), ffmpeg-decoded formats, the results file, Mixxx's Comment notes, and
the window marking damaged tracks red."""

import os
import random
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_db  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from cr8txxx.db import crates, tracks  # noqa: E402
from cr8txxx.db.mixxx import Library  # noqa: E402
from cr8txxx.scan import checker, ffmpeg  # noqa: E402
from cr8txxx.scan.cache import Checks  # noqa: E402
from cr8txxx.scan.worker import ScanWorker  # noqa: E402
from cr8txxx.ui import main_window as mw  # noqa: E402
from cr8txxx.ui.track_model import BAD_ROW, KEYS  # noqa: E402

HEADER = b"\xff\xfb\x90\x00"  # MPEG-1 Layer III, 128 kbps, 44.1 kHz: 417-byte frames
FRAME = 417


def mp3(frames: int = 400, seed: int = 1) -> bytearray:
    rnd = random.Random(seed)
    return bytearray(b"".join(HEADER + rnd.randbytes(FRAME - 4) for _ in range(frames)))


def repeated(data: bytearray) -> bytearray:
    """FMM's damage: a block overwritten with the block before it (60 frames, ~1.6 s)."""
    bad = bytearray(data)
    bad[200 * FRAME : 260 * FRAME] = data[140 * FRAME : 200 * FRAME]
    return bad


def with_break(data: bytearray) -> bytearray:
    return data[: 200 * FRAME] + bytearray(100) + data[200 * FRAME :]


def test_good_mp3() -> None:
    found = checker.check_mp3(bytes(mp3()))
    assert found["frames"] == 400 and not found["repeats"] and not found["breaks"]
    assert found["bitrate"] == 128 and found["rate"] == 44100


def test_repeated_block_is_damage() -> None:
    found = checker.check_mp3(bytes(repeated(mp3())))
    (r,) = found["repeats"]
    assert r["seconds"] > 1.5 and r["copy_of"] < r["at"]
    assert "repeated at" in checker.describe({**found, "status": "damaged"})


def test_silence_is_never_a_repeat() -> None:
    silent = bytearray((HEADER + bytes(FRAME - 4)) * 400)
    assert not checker.check_mp3(bytes(silent))["repeats"]


def test_break_is_suspect(tmp_path: Path) -> None:
    f = tmp_path / "b.mp3"
    f.write_bytes(with_break(mp3()))
    result = checker.check_file(str(f), None)
    assert result["status"] == "suspect" and result["breaks"] == 1


def test_file_statuses_without_ffmpeg(tmp_path: Path) -> None:
    good, bad, other = tmp_path / "g.mp3", tmp_path / "d.mp3", tmp_path / "x.flac"
    good.write_bytes(mp3())
    bad.write_bytes(repeated(mp3()))
    other.write_bytes(b"fLaC")
    assert checker.check_file(str(good), None)["status"] == "ok"
    assert checker.check_file(str(bad), None)["status"] == "damaged"
    assert checker.check_file(str(other), None)["status"] == "unchecked"
    assert checker.check_file(str(tmp_path / "gone.mp3"), None)["status"] == "unreadable"


@pytest.mark.skipif(not shutil.which("ffmpeg") and not ffmpeg.locate(), reason="no ffmpeg")
def test_corrupt_flac_is_damaged(tmp_path: Path) -> None:
    tool = ffmpeg.locate()
    assert tool
    good = tmp_path / "tone.flac"
    tone = "sine=frequency=440:duration=4"
    subprocess.run([tool.ffmpeg, "-v", "error", "-f", "lavfi", "-i", tone, str(good)], check=True)
    assert checker.check_file(str(good), tool)["status"] == "ok"
    data = bytearray(good.read_bytes())
    mid = len(data) // 2
    data[mid : mid + 2000] = bytes(2000)
    bad = tmp_path / "broken.flac"
    bad.write_bytes(data)
    result = checker.check_file(str(bad), tool)
    assert result["status"] == "damaged" and result["errors"] > 0
    assert checker.facts_line(result).startswith("FLAC")


def test_cache_rechecks_only_changed_files(tmp_path: Path) -> None:
    f = tmp_path / "a.mp3"
    f.write_bytes(mp3())
    checks = Checks(tmp_path / "checks.sqlite")
    assert not checks.current(str(f), False)
    checks.put(str(f), checker.check_file(str(f), None))
    assert checks.current(str(f), False)
    f.write_bytes(repeated(mp3()))  # replaced (size the same, time not)
    os.utime(f, (1, 1))
    assert not checks.current(str(f), False)
    checks.put(str(tmp_path / "x.flac"), {"v": checker.VERSION, "status": "unchecked"})
    assert not checks.current(str(tmp_path / "x.flac"), True)  # ffmpeg now there: again
    checks.forget_all()
    assert checks.all() == {}


def test_worker_checks_and_skips(tmp_path: Path) -> None:
    good, bad = tmp_path / "g.mp3", tmp_path / "d.mp3"
    good.write_bytes(mp3())
    bad.write_bytes(repeated(mp3()))
    db = tmp_path / "c.sqlite"
    seen: list[tuple[str, str]] = []
    done: list[dict] = []
    w = ScanWorker([str(good), str(bad)], cache_path=db)
    w.checked.connect(lambda p, s: seen.append((p, s)))
    w.done.connect(done.append)
    w.run()  # in this thread
    assert sorted(s for _p, s in seen) == ["damaged", "ok"] and done[0]["checked"] == 2
    again = ScanWorker([str(good), str(bad)], cache_path=db)
    again.done.connect(done.append)
    again.run()
    assert done[1]["checked"] == 0 and done[1]["skipped"] == 2


def test_damage_note_text() -> None:
    note = tracks.DAMAGE_NOTE
    assert tracks.with_note("") == note
    assert tracks.with_note("peak time") == f"{note} | peak time"
    assert tracks.with_note(tracks.with_note("x")) == f"{note} | x"
    assert tracks.without_note(f"{note} | peak time") == "peak time"
    assert tracks.without_note(note) == ""
    assert tracks.without_note("plain") == "plain"


def test_note_damage_in_mixxx(lib: Library, running: dict[str, bool]) -> None:
    tracks.update_metadata(lib, [2], {"comment": "warm-up only"})
    assert tracks.note_damage(lib, [1, 2], []) == (2, 0)
    comments = {t.id: t.get("comment") for t in tracks.all_tracks(lib)}
    assert comments[1] == tracks.DAMAGE_NOTE
    assert comments[2] == f"{tracks.DAMAGE_NOTE} | warm-up only"
    assert tracks.note_damage(lib, [1, 2], []) == (0, 0)  # never twice
    assert tracks.note_damage(lib, [1], [2]) == (0, 1)  # replaced with a good file
    assert tracks.by_ids(lib, [2])[0].get("comment") == "warm-up only"


# --- In the window --------------------------------------------------------------------------


@pytest.fixture
def win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, running: dict[str, bool]):  # type: ignore[no-untyped-def]
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(Library.__init__, "__defaults__", (lambda: running["mixxx"],))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(ffmpeg, "locate", lambda folder="": None)
    monkeypatch.setattr(mw.MainWindow, "show_setup", lambda self: None)
    db = make_db(tmp_path)
    music = tmp_path / "Music"
    files = sorted(music.glob("*.mp3"))
    files[0].write_bytes(repeated(mp3(seed=1)))  # Daft Punk: damaged
    files[1].write_bytes(mp3(seed=2))  # Moby: fine
    files[2].write_bytes(with_break(mp3(seed=3)))  # Air: suspect
    w = mw.MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1400, 900)
    w.show()
    w.open_database(db)
    yield w
    w.close()


def scan(w: mw.MainWindow) -> None:
    w.start_scan()
    assert w.scan_worker is not None
    w.scan_worker.wait(20000)
    QApplication.processEvents()  # the worker's signals arrive
    QApplication.processEvents()


def row_of(pane, track_id: int) -> int:  # type: ignore[no-untyped-def]
    return next(i for i, t in enumerate(pane.model.rows) if t.id == track_id)


def test_scan_marks_red_and_notes(win: mw.MainWindow) -> None:
    scan(win)
    assert win.scan_worker is None
    model = win.library.model
    win.show_view(mw.ALL)
    r = row_of(win.library, 1)
    assert model.data(
        model.index(r, KEYS.index("title")), Qt.ItemDataRole.BackgroundRole
    ).color() == QColor(BAD_ROW)  # noqa: E501
    fine = row_of(win.library, 2)
    assert model.data(model.index(fine, 1), Qt.ItemDataRole.BackgroundRole) is None
    # noted in Mixxx's Comment, the damaged one only
    comments = {t.id: t.get("comment") for t in tracks.all_tracks(win.lib)}
    assert comments[1] == tracks.DAMAGE_NOTE and not comments[2] and not comments[3]
    # the scan view lists damaged and suspect
    win.show_view(mw.SCAN)
    assert sorted(t.id for t in win.library.model.rows) == [1, 3]
    assert win.tab_buttons[mw.SCAN].text().endswith("1")
    # red in a crate too
    win.crate_list.select(1)
    cm = win.crate_pane.model
    r = row_of(win.crate_pane, 1)
    assert cm.data(cm.index(r, 1), Qt.ItemDataRole.BackgroundRole).color() == QColor(BAD_ROW)


def test_red_stays_after_restart(win: mw.MainWindow, tmp_path: Path) -> None:
    scan(win)
    win.close()
    again = mw.MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    again.open_database(tmp_path / "mixxxdb.sqlite")
    m = again.library.model
    r = row_of(again.library, 1)
    assert m.data(m.index(r, 1), Qt.ItemDataRole.BackgroundRole).color() == QColor(BAD_ROW)


def test_notes_wait_for_mixxx_to_quit(win: mw.MainWindow, running: dict[str, bool]) -> None:
    running["mixxx"] = True
    scan(win)
    assert win.notes_waiting == 1 and "damage note" in win.banner.text()
    assert not tracks.noted(tracks.by_ids(win.lib, [1])[0].get("comment"))
    running["mixxx"] = False
    win._check_guard()  # what the 3-second timer does
    assert tracks.noted(tracks.by_ids(win.lib, [1])[0].get("comment"))
    assert win.notes_waiting == 0


def test_replaced_file_clears_red_and_note(win: mw.MainWindow, tmp_path: Path) -> None:
    scan(win)
    path = tracks.by_ids(win.lib, [1])[0].path
    Path(path).write_bytes(mp3(seed=9))  # a good copy in its place
    scan(win)
    assert not tracks.noted(tracks.by_ids(win.lib, [1])[0].get("comment"))
    win.show_view(mw.ALL)
    m = win.library.model
    assert m.data(m.index(row_of(win.library, 1), 1), Qt.ItemDataRole.BackgroundRole) is None


def test_damaged_to_crate(win: mw.MainWindow) -> None:
    scan(win)
    win.damaged_to_crate()
    (crate,) = [c for c in crates.list_crates(win.lib) if c.name == mw.DAMAGED_CRATE]
    assert crate.tracks == 1 and win.crate_id == crate.id
