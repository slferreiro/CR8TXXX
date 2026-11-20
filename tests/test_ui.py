# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""The window (layout A), offscreen: the three panes, crates, text size, window placement,
and every drag and drop path."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_db  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from cr8txxx.db import crates, tracks  # noqa: E402
from cr8txxx.db.mixxx import Library  # noqa: E402
from cr8txxx.ui import main_window as mw  # noqa: E402
from cr8txxx.ui import theme  # noqa: E402
from cr8txxx.ui.main_window import MainWindow  # noqa: E402
from cr8txxx.ui.track_model import MIME, files_from_mime, ids_from_mime  # noqa: E402


@pytest.fixture
def win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(Library.__init__, "__defaults__", (lambda: False,))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    w.resize(1400, 900)
    w.show()
    w.open_database(make_db(tmp_path))
    QApplication.processEvents()
    yield w
    w.close()


def drop(widget: QWidget, pos: QPoint, mime: QMimeData) -> bool:
    ev = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)  # fmt: skip
    widget.dropEvent(ev)
    return ev.isAccepted()


def track_mime(*ids: int) -> QMimeData:
    mime = QMimeData()
    mime.setData(MIME, ",".join(map(str, ids)).encode())
    return mime


def file_mime(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def crate_pos(w: MainWindow, crate_id: int) -> QPoint:
    cl = w.crate_list
    for i in range(cl.count()):
        if cl.item(i).data(Qt.ItemDataRole.UserRole).id == crate_id:
            return cl.visualItemRect(cl.item(i)).center()
    raise AssertionError("crate not listed")


def test_three_panes(win: MainWindow) -> None:
    assert win.library.model.rowCount() == 3
    assert win.tab_buttons[mw.ALL].text().endswith("3")
    assert win.crate_list.count() == 1 and win.crate_count.text() == "1"
    assert win.crate_name.text() == "No crate selected"
    win.crate_list.select(1)
    assert win.crate_id == 1 and win.crate_pane.model.rowCount() == 2
    assert win.crate_name.text() == "Warmup" and win.crate_summary.text().startswith("2 tracks")
    win.search.setText("moby")
    assert win.library.proxy.rowCount() == 1
    assert win.crate_pane.proxy.rowCount() == 2  # the search is for the library pane


def test_views(win: MainWindow) -> None:
    win.show_view(mw.HIDDEN)
    assert win.library.stack.currentWidget() is win.library.empty
    tracks.hide(win.lib, [1])
    win.reload()
    assert win.library.model.rowCount() == 1 and win.tab_buttons[mw.HIDDEN].text().endswith("1")
    win.show_view(mw.SCAN)
    assert win.library.empty_title.text() == "Not scanned yet"
    assert not win.scan_bar.isHidden()
    win.show_view(mw.ALL)
    assert win.library.model.rowCount() == 2


def test_drag_out_carries_ids_and_files(win: MainWindow) -> None:
    model = win.library.model
    mime = model.mimeData([model.index(r, 1) for r in range(3)])
    assert sorted(ids_from_mime(mime)) == [1, 2, 3]
    assert len(mime.urls()) == 3 and all(os.path.exists(u.toLocalFile()) for u in mime.urls())
    assert files_from_mime(mime) == []  # our own drag isn't mistaken for a Finder drop


def test_library_tracks_onto_crate_in_list(win: MainWindow) -> None:
    assert drop(win.crate_list, crate_pos(win, 1), track_mime(3))
    assert crates.get(win.lib, 1).tracks == 3


def test_library_tracks_into_crate_pane(win: MainWindow) -> None:
    win.crate_list.select(1)
    assert drop(win.crate_pane.table, QPoint(20, 20), track_mime(3))
    assert win.crate_pane.model.rowCount() == 3
    assert win.crate_summary.text().startswith("3 tracks")


def test_crate_pane_ignores_tracks_with_no_crate(win: MainWindow) -> None:
    drop(win.crate_pane.table, QPoint(20, 20), track_mime(3))
    assert crates.get(win.lib, 1).tracks == 2


def test_finder_folder_onto_crate_in_list(win: MainWindow, tmp_path: Path) -> None:
    folder = tmp_path / "Music" / "New Album"
    folder.mkdir()
    for n in (1, 2):
        (folder / f"{n}.mp3").write_bytes(b"\0" * 100)
    (folder / "notes.txt").write_text("x")
    assert drop(win.crate_list, crate_pos(win, 1), file_mime(folder))
    assert crates.get(win.lib, 1).tracks == 4 and len(tracks.all_tracks(win.lib)) == 5


def test_finder_files_onto_library(win: MainWindow, tmp_path: Path) -> None:
    f = tmp_path / "Music" / "dropped.flac"
    f.write_bytes(b"\0" * 10)
    assert drop(win.library.table, QPoint(20, 20), file_mime(f))
    assert win.library.model.rowCount() == 4
    assert crates.get(win.lib, 1).tracks == 2


def test_finder_files_onto_crate_pane(win: MainWindow, tmp_path: Path) -> None:
    f = tmp_path / "Music" / "dropped.flac"
    f.write_bytes(b"\0" * 10)
    win.crate_list.select(1)
    assert drop(win.crate_pane.table, QPoint(20, 20), file_mime(f))
    assert any(t.path == str(f) for t in tracks.in_crate(win.lib, 1))


def test_remove_from_crate(win: MainWindow) -> None:
    win.crate_list.select(1)
    win.remove_from_crate(1, [1])
    assert win.crate_pane.model.rowCount() == 1


def test_deleted_crate_clears_pane(win: MainWindow) -> None:
    win.crate_list.select(1)
    crates.delete(win.lib, 1)
    win.reload()
    assert win.crate_id == 0 and win.crate_name.text() == "No crate selected"


def test_read_only_disables_writes(win: MainWindow) -> None:
    win.lib._running = lambda: True
    win._check_guard()
    assert not win.a_new_crate.isEnabled() and not win.banner.isHidden()
    win.lib._running = lambda: False
    win._check_guard()
    assert win.a_new_crate.isEnabled() and win.banner.isHidden()


def test_text_size_grows_everything(win: MainWindow) -> None:
    before = win.library.table.verticalHeader().defaultSectionSize()
    win.set_text_scale(1.4)
    after = win.library.table.verticalHeader().defaultSectionSize()
    assert after > before and theme.scale() == 1.4
    assert win.settings.value("text_scale") in (1.4, "1.4")
    win.set_text_scale(None)
    assert win.library.table.verticalHeader().defaultSectionSize() == before


def test_window_off_every_screen_is_noticed(win: MainWindow) -> None:
    assert win._on_a_screen()
    win.move(60000, 60000)
    assert not win._on_a_screen()


def test_layout_is_remembered(win: MainWindow, tmp_path: Path) -> None:
    win.main_split.setSizes([500, 900])
    saved = win.main_split.saveState()
    win.close()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    assert settings.value("split_main") == saved
    assert settings.value("geometry") is not None
    again = MainWindow(settings)
    restored: list[object] = []
    again.main_split.restoreState = lambda st: restored.append(st) or True  # type: ignore[method-assign]
    again.show()
    QApplication.processEvents()
    assert restored and restored[0] == saved


def test_tests_leave_real_settings_alone(win: MainWindow) -> None:
    real = QSettings("CR8TXXX", "CR8TXXX")
    assert "pytest" not in str(real.value("database", ""))


def test_columns_fill_the_pane(win: MainWindow) -> None:
    from cr8txxx.ui.track_model import KEYS

    pane = win.library
    header = pane.table.horizontalHeader()
    shown = [i for i in range(len(KEYS)) if not pane.table.isColumnHidden(i)]
    total = sum(header.sectionSize(i) for i in shown)
    width = pane.table.viewport().width()
    assert total >= width - len(shown)  # no gap at the right
    if total > width + len(shown):  # too narrow: every text column at its minimum
        from cr8txxx.ui.track_pane import MIN_FLEX

        for key in ("artist", "title", "album", "genre", "path"):
            assert header.sectionSize(KEYS.index(key)) == theme.px(MIN_FLEX)

    bpm = header.sectionSize(KEYS.index("bpm"))
    win.set_text_scale(1.4)
    assert header.sectionSize(KEYS.index("bpm")) > bpm  # fixed columns grow with the text


def test_share_floors_small_columns() -> None:
    from cr8txxx.ui.track_pane import _share

    assert _share(1000, {"a": 1, "b": 1}, 70) == {"a": 500, "b": 500}
    got = _share(300, {"a": 10, "b": 1, "c": 1}, 70)
    assert got["b"] == got["c"] == 70 and got["a"] == 160


def test_hand_resized_columns_stay(win: MainWindow) -> None:
    from cr8txxx.ui.track_model import KEYS

    pane = win.library
    header = pane.table.horizontalHeader()
    header.resizeSection(KEYS.index("title"), 500)
    assert not pane.auto_fit
    win.resize(1300, 850)
    QApplication.processEvents()
    assert header.sectionSize(KEYS.index("title")) == 500
    pane.fit_again()
    assert pane.auto_fit and header.sectionSize(KEYS.index("title")) != 500


def test_narrow_pane_drops_low_priority_columns(win: MainWindow) -> None:
    from cr8txxx.ui.track_model import KEYS

    pane = win.library
    win.main_split.setSizes([450, 900])
    QApplication.processEvents()
    assert "path" in pane.dropped and pane.table.isColumnHidden(KEYS.index("path"))
    assert "path" not in pane.chosen_hidden  # still wanted: back when there's room
    assert not pane.table.isColumnHidden(KEYS.index("title"))
    pane.set_column_shown("bpm", False)
    assert pane.table.isColumnHidden(KEYS.index("bpm")) and "bpm" in pane.chosen_hidden


def test_about_shows_licence_and_notices(win: MainWindow) -> None:
    from cr8txxx.ui.about import AboutDialog, resources

    d = AboutDialog(win)
    assert "Qt" in d.notices.toPlainText() and "tinytag" in d.notices.toPlainText()
    assert (resources() / "LICENSE").read_text().startswith(" " * 20 + "GNU GENERAL PUBLIC")
    assert (resources() / "licenses" / "LGPL-3.0.txt").exists()
