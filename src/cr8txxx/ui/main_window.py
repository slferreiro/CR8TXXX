# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""CR8TXXX's window (layout A):

    ┌ CR8TXXX  [toolbar buttons] ─────────────────────── [search] ┐
    │ banner: why the library can't be changed right now          │
    ├ [All][Missing][Hidden][Scan] ───────┬ CRATES ─────── [+ New] ┤
    │ library tracks                      │ crate list             │
    │                                     ├ CRATE · name · summary ┤
    │                                     │ the crate's tracks     │
    └─────────────────────────────────────┴────────────────────────┘

Drag and drop:
- library tracks → a crate in the list, or into the crate pane: added to that crate
- files/folders from Finder → the library pane: added to the library; → a crate or the crate
  pane: added to the library and that crate
- tracks → Finder or another app: the files (copied, never moved)
"""

import csv
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cr8txxx import paths
from cr8txxx.db import crates, tracks
from cr8txxx.db.crates import CrateError
from cr8txxx.db.mixxx import AccessDenied, Library, NotMixxxDB, ReadOnly, find_database
from cr8txxx.scan import checker, ffmpeg
from cr8txxx.scan.cache import BAD, WARN, Checks
from cr8txxx.scan.worker import FolderScan, ScanWorker
from cr8txxx.ui import icons, theme
from cr8txxx.ui.crate_list import CrateList
from cr8txxx.ui.edit_dialog import EditDialog
from cr8txxx.ui.relocate_dialog import RelocateDialog
from cr8txxx.ui.track_model import (
    CHECK_WORDS,
    CRATE_HIDDEN,
    HEADINGS,
    KEYS,
    LIBRARY_HIDDEN,
    VERIFIED,
    clock,
)
from cr8txxx.ui.track_pane import TrackPane

SETTING_DB = "database"
GUARD_EVERY_MS = 3000
ALL, MISSING, HIDDEN, SCAN = "all", "missing", "hidden", "scan"
VIEWS = [(ALL, "All Tracks", "tracks"), (MISSING, "Missing", "missing"),
         (HIDDEN, "Hidden", "hidden"), (SCAN, "Damaged Scan", "scan")]  # fmt: skip
EMPTY = {
    MISSING: ("No missing files", "Every track's file is where Mixxx expects it. When files "
              "move, they show here, ready for Relocate."),
    HIDDEN: ("No hidden tracks", "Tracks removed with Hide show here, with their cues and "
             "crates kept, and can be brought back."),
    SCAN: ("Not scanned yet", "Scan for Damaged Files checks every file in the library for "
           "repeated blocks, breaks and decoding errors (FMM's checker). Damaged files are "
           "marked red everywhere, and noted in Mixxx's Comment."),
}  # fmt: skip
DAMAGED_CRATE = "Damaged Files"
MIN_W, MIN_H = 1100, 680


def _label(text: str, name: str, size: float = theme.BASE_PX, bold: bool = False,
           spacing: float = 0) -> QLabel:  # fmt: skip
    label = QLabel(text)
    label.setObjectName(name)
    label.setProperty("fontSpec", (size, bold, spacing))
    label.setFont(theme.font(size, bold, spacing))
    return label


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        # Tests pass their own settings file, so they never change the app's real settings
        self.settings = settings or QSettings(paths.APP_NAME, paths.APP_NAME)
        self.setWindowTitle(paths.APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.lib: Library | None = None
        self.view = ALL
        self.crate_id = 0
        self._write_actions: list[QAction] = []
        self._labels: list[QLabel] = []
        self._splits_placed = False
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply(app, self._saved_scale())

        self._actions()
        self._build()
        self._place()

        self.guard = QTimer(self)
        self.guard.timeout.connect(self._check_guard)
        self.guard.start(GUARD_EVERY_MS)

    # --- Building the window -----------------------------------------------------------------

    def _l(self, *args: object, **kwargs: object) -> QLabel:
        label = _label(*args, **kwargs)  # type: ignore[arg-type]
        self._labels.append(label)
        return label

    def _tool(self, action: QAction) -> QToolButton:
        b = QToolButton()
        b.setObjectName("ToolBarButton")
        b.setDefaultAction(action)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tools.append(b)
        return b

    def _build(self) -> None:
        self._tools: list[QToolButton] = []

        # Header strip: wordmark, toolbar buttons, search
        header = QWidget()
        header.setObjectName("Header")
        self.header_row = QHBoxLayout(header)
        self.logo = QLabel()
        self.logo.setTextFormat(Qt.TextFormat.RichText)
        self.header_row.addWidget(self.logo)
        for act in (self.a_add_files, self.a_add_folder, self.a_find_new, self.a_new_crate,
                    self.a_edit, self.a_relocate, self.a_refresh):  # fmt: skip
            self.header_row.addWidget(self._tool(act))
        self.header_row.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search artist, title, album, genre, path…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(
            icons.icon("search", theme.DIM), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.textChanged.connect(self._filter)
        self.header_row.addWidget(self.search)

        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()

        # Left: the library
        self.library = TrackPane(LIBRARY_HIDDEN)
        self.tabs = QButtonGroup(self)
        self.tabs.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for kind, label, icon in VIEWS:
            b = QPushButton(label)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIcon(icons.icon(icon, theme.RED if kind == MISSING else theme.BLUE))
            b.clicked.connect(lambda _c=False, k=kind: self.show_view(k))
            self.tabs.addButton(b)
            self.library.header_row.addWidget(b)
            self.tab_buttons[kind] = b
        self.tab_buttons[ALL].setChecked(True)
        self.library.header_row.addStretch()
        self._build_scan_bar()
        self.library.table.on_files = lambda files: self.add_paths(0, files)
        self._table_menus(self.library)

        # Top right: the crates
        self.crate_frame = QFrame()
        self.crate_frame.setObjectName("Pane")
        crate_header = QWidget()
        crate_header.setObjectName("PaneHeader")
        self.crate_header_row = QHBoxLayout(crate_header)
        self.crate_header_row.addWidget(self._l("CRATES", "PaneTitle", 11, True, 1.2))
        self.crate_count = self._l("", "Dim", 12)
        self.crate_header_row.addWidget(self.crate_count)
        self.crate_header_row.addStretch()
        self.crate_header_row.addWidget(self._tool(self.a_new_crate_small))
        self.crate_list = CrateList()
        self.crate_list.crate_chosen.connect(self.show_crate)
        self.crate_list.tracks_dropped.connect(self.add_to_crate)
        self.crate_list.files_dropped.connect(self.add_paths)
        self.crate_list.menu_asked.connect(self.crate_menu)
        col = QVBoxLayout(self.crate_frame)
        col.setContentsMargins(1, 1, 1, 1)
        col.setSpacing(0)
        col.addWidget(crate_header)
        col.addWidget(self.crate_list, 1)

        # Bottom right: the selected crate's tracks
        self.crate_pane = TrackPane(CRATE_HIDDEN)
        self.crate_pane.header_row.addWidget(self._l("CRATE", "CrateTag", 11, True, 1.2))
        self.crate_name = self._l("", "Strong", 14, True)
        self.crate_summary = self._l("", "Dim", 12)
        self.crate_pane.header_row.addWidget(self.crate_name)
        self.crate_pane.header_row.addWidget(self.crate_summary)
        self.crate_pane.header_row.addStretch()
        self.crate_pane.table.on_tracks = lambda ids: self.add_to_crate(self.crate_id, ids)
        self.crate_pane.table.on_files = lambda files: self.add_paths(self.crate_id, files)
        self._table_menus(self.crate_pane)

        self.right_split = QSplitter(Qt.Orientation.Vertical)
        self.right_split.addWidget(self.crate_frame)
        self.right_split.addWidget(self.crate_pane)
        self.right_split.setChildrenCollapsible(False)
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.addWidget(self.library)
        self.main_split.addWidget(self.right_split)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setStretchFactor(0, 55)
        self.main_split.setStretchFactor(1, 45)

        body = QWidget()
        self.body_box = QVBoxLayout(body)
        self.body_box.addWidget(self.main_split)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(header)
        outer.addWidget(self.banner)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)

        self.status_counts = QLabel()
        self.status_toast = QLabel()
        self.status_path = QLabel()
        self.status_toast.setStyleSheet(f"color: {theme.GREEN};")
        self.statusBar().addWidget(self.status_counts)
        self.statusBar().addWidget(self.status_toast, 1)
        self.statusBar().addPermanentWidget(self.status_path)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self.status_toast.setText(""))

        self.show_crate(0)
        self._restyle()

    def _build_scan_bar(self) -> None:
        """The scan's controls, under the library's tabs in the Damaged Scan view."""
        self.scan_worker: ScanWorker | None = None
        self.notes_waiting = 0
        self.checks: dict[str, dict[str, object]] = {}
        bar = QWidget()
        bar.setObjectName("ScanBar")
        self.scan_row = QHBoxLayout(bar)
        self.scan_btn = QPushButton("Scan for Damaged Files")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.setIcon(icons.icon("scan", "#ffffff"))
        self.scan_btn.clicked.connect(lambda: self.start_scan(rescan=False))
        self.rescan_btn = QPushButton("Rescan Everything")
        self.rescan_btn.setToolTip("Check every file again, not only new or changed ones")
        self.rescan_btn.clicked.connect(lambda: self.start_scan(rescan=True))
        self.scan_progress = QProgressBar()
        self.scan_progress.setTextVisible(True)
        self.scan_progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_scan)
        self.cancel_btn.hide()
        self.scan_summary = QLabel()
        self.scan_summary.setObjectName("ScanSummary")
        self.scan_crate_btn = QPushButton(f"Put in Crate “{DAMAGED_CRATE}”")
        self.scan_crate_btn.clicked.connect(self.damaged_to_crate)
        self._write_buttons = [self.scan_crate_btn]
        self.scan_export_btn = QPushButton("Export CSV…")
        self.scan_export_btn.clicked.connect(self.export_scan)
        for w in (self.scan_btn, self.rescan_btn, self.scan_progress, self.cancel_btn):
            self.scan_row.addWidget(w)
        self.scan_row.addWidget(self.scan_summary, 1)
        self.scan_row.addWidget(self.scan_crate_btn)
        self.scan_row.addWidget(self.scan_export_btn)
        self.scan_bar = bar
        self.library.bars.addWidget(bar)
        bar.hide()

    def _table_menus(self, pane: TrackPane) -> None:
        t = pane.table
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(lambda pos, p=pane: self.track_menu(p, pos))
        t.doubleClicked.connect(lambda _i, p=pane: self.edit_tracks(p.selected_tracks()))
        header = t.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(lambda pos, p=pane: self.column_menu(p, pos))
        t.selectionModel().selectionChanged.connect(lambda *_: self._status())

    def _restyle(self) -> None:
        """Sizes that follow the text size."""
        s = theme.px
        self.logo.setText(
            f'<span style="font-size:{s(19)}px; font-weight:700; letter-spacing:1px;">'
            f'<span style="color:{theme.BRIGHT};">CR8T</span>'
            f'<span style="color:{theme.BLUE};">XXX</span></span>'
        )
        self.header_row.setContentsMargins(s(14), s(8), s(14), s(8))
        self.header_row.setSpacing(s(6))
        self.logo.setContentsMargins(0, 0, s(14), 0)
        self.search.setMinimumWidth(s(300))
        self.search.setMaximumWidth(s(420))
        for b in self._tools:
            b.setIconSize(theme_size(15))
        for b in self.tab_buttons.values():
            b.setIconSize(theme_size(14))
        for label in self._labels:
            size, bold, spacing = label.property("fontSpec")
            label.setFont(theme.font(size, bold, spacing))
        self.scan_row.setContentsMargins(s(10), s(7), s(10), s(7))
        self.scan_row.setSpacing(s(8))
        self.scan_progress.setMinimumWidth(s(220))
        self.crate_header_row.setContentsMargins(s(10), s(6), s(10), s(6))
        self.crate_header_row.setSpacing(s(6))
        self.body_box.setContentsMargins(s(8), s(8), s(8), s(8))
        for pane in (self.library, self.crate_pane):
            pane.restyle()
        self.crate_list.doItemsLayout()
        self.crate_list.viewport().update()

    # --- Window size and text size -----------------------------------------------------------

    def _place(self) -> None:
        """First launch: 85% of the screen, centred. Later: where it was, if that screen is
        still there."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area:
            self.setMinimumSize(min(MIN_W, area.width()), min(MIN_H, area.height()))
        geometry = self.settings.value("geometry")
        if geometry is not None and self.restoreGeometry(geometry) and self._on_a_screen():
            pass
        else:
            theme.fit_to_screen(self, 0.85, 0.85, MIN_W, MIN_H)
            if area:
                frame = self.frameGeometry()
                frame.moveCenter(area.center())
                self.move(frame.topLeft())
        for name, pane in (("library", self.library), ("crate", self.crate_pane)):
            pane.restore_state(
                self.settings.value(f"columns_{name}"),
                self.settings.value(f"columns_{name}_auto", True),
                self.settings.value(f"columns_{name}_hidden"),
            )

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._splits_placed:  # once laid out at its real size (not before)
            self._splits_placed = True
            self._restore_splits()

    def _restore_splits(self) -> None:
        for key, split, default in (("split_main", self.main_split, [55, 45]),
                                    ("split_right", self.right_split, [30, 70])):  # fmt: skip
            state = self.settings.value(key)
            if state is None or not split.restoreState(state):
                total = max(1, split.width() if split.orientation() == Qt.Orientation.Horizontal
                            else split.height())  # fmt: skip
                split.setSizes([total * d // 100 for d in default])

    def _on_a_screen(self) -> bool:
        frame = self.frameGeometry()
        return any(s.availableGeometry().intersects(frame) for s in QGuiApplication.screens())

    def _saved_scale(self) -> float:
        raw = self.settings.value("text_scale", "")
        try:
            return float(raw) if raw not in ("", None) else theme.auto_scale()  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return theme.auto_scale()

    def set_text_scale(self, value: float | None) -> None:
        """A new text size (None: the screen's default)."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        if value is None:
            self.settings.setValue("text_scale", "")
            value = theme.auto_scale()
        else:
            self.settings.setValue("text_scale", value)
        theme.apply(app, value)
        self._restyle()

    def _step_text(self, step: int) -> None:
        now = theme.scale()
        options = theme.SCALES
        nearest = min(range(len(options)), key=lambda i: abs(options[i] - now))
        i = max(0, min(len(options) - 1, nearest + step))
        self.set_text_scale(options[i])
        self.toast(f"Text size {options[i]:g}×")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("split_main", self.main_split.saveState())
        self.settings.setValue("split_right", self.right_split.saveState())
        self.settings.setValue("columns_library", self.library.save_state())
        self.settings.setValue("columns_crate", self.crate_pane.save_state())
        for name, pane in (("library", self.library), ("crate", self.crate_pane)):
            self.settings.setValue(f"columns_{name}_auto", pane.auto_fit)
            self.settings.setValue(f"columns_{name}_hidden", sorted(pane.chosen_hidden))
        if self.lib:
            self.lib.close()
        super().closeEvent(event)

    # --- Menus --------------------------------------------------------------------------------

    def _action(self, text: str, slot: Callable[[], object], key: str = "", write: bool = False,
                icon: str = "", color: str = theme.BLUE) -> QAction:  # fmt: skip
        act = QAction(text, self)
        act.triggered.connect(lambda _c=False: slot())
        if key:
            act.setShortcut(QKeySequence(key))
        if icon:
            act.setIcon(icons.icon(icon, color))
        if write:
            self._write_actions.append(act)
        return act

    def _actions(self) -> None:
        a = self._action
        self.a_open = a("Open Database…", self.choose_database, "Ctrl+O")
        self.a_add_files = a("Add Files", self.add_files_dialog, "Ctrl+Shift+A", True, "files")
        self.a_add_folder = a("Add Folder", self.add_folder_dialog, "", True, "folder")
        self.a_find_new = a("Find New Songs", self.find_new_songs, "Ctrl+Shift+N", True, "newsongs")
        self.a_find_new.setToolTip("Look in Mixxx's music folders for songs not in the library yet")
        self.a_new_crate = a("New Crate", self.new_crate, "Ctrl+N", True, "crate", theme.ORANGE)
        self.a_new_crate_small = a("New", self.new_crate, "", True, "plus")
        self.a_import = a("Import M3U as Crate…", self.import_m3u, "", True)
        self.a_edit = a("Edit", self.edit_selected, "Ctrl+I", True, "edit")
        self.a_hide = a("Hide from Library", self.hide_selected, "", True)
        self.a_relocate = a("Relocate", self.relocate, "", True, "relocate")
        self.a_refresh = a("Refresh", self.reload, "Ctrl+R", False, "refresh")
        self.a_reveal = a("Reveal in Finder", self.reveal_selected, "Ctrl+Shift+R")
        self.a_backup = a("Show Backups in Finder", self.show_backups)
        self.a_bigger = a("Bigger", lambda: self._step_text(1), "Ctrl++")
        self.a_smaller = a("Smaller", lambda: self._step_text(-1), "Ctrl+-")
        self.a_actual = a("Actual Size", lambda: self.set_text_scale(None), "Ctrl+0")

        bar = self.menuBar()
        m = bar.addMenu("File")
        for act in (self.a_open, None, self.a_add_files, self.a_add_folder, None, self.a_import,
                    None, self.a_backup):  # fmt: skip
            m.addSeparator() if act is None else m.addAction(act)
        m = bar.addMenu("Library")
        for act in (self.a_find_new, None, self.a_edit, self.a_reveal, None, self.a_hide, None,
                    self.a_relocate, None, self.a_refresh):  # fmt: skip
            m.addSeparator() if act is None else m.addAction(act)
        m = bar.addMenu("Crates")
        m.addAction(self.a_new_crate)
        m.addAction(self.a_import)
        m = bar.addMenu("View")
        size = m.addMenu("Text Size")
        for act in (self.a_bigger, self.a_smaller, self.a_actual):
            size.addAction(act)
        m = bar.addMenu("Help")
        m.addAction("Set Up CR8TXXX…", self.show_setup)
        about = m.addAction("About CR8TXXX", self.show_about)
        about.setMenuRole(QAction.MenuRole.AboutRole)  # the app menu's "About CR8TXXX"

    # --- Opening the database ----------------------------------------------------------------

    def open_first(self) -> None:
        """At startup: first-run setup once, then the database chosen before, else
        Mixxx's own; ask if none."""
        if not self.settings.value("setup_done"):
            self.show_setup()
            self.settings.setValue("setup_done", True)
        path = find_database(str(self.settings.value(SETTING_DB, "") or ""))
        if path is None:
            QMessageBox.information(
                self, "No Mixxx Library Found",
                "CR8TXXX couldn't find a Mixxx library on this Mac.\n\nOpen Mixxx once (and "
                "add your music folder in Preferences › Library), or choose a mixxxdb.sqlite "
                "file.",
            )  # fmt: skip
            self.choose_database()
            return
        self.open_database(path)

    def show_about(self) -> None:
        from cr8txxx.ui.about import AboutDialog

        AboutDialog(self).exec()

    def show_setup(self) -> None:
        """First-run setup: Mixxx's library and ffmpeg, put right with the person's OK."""
        from cr8txxx.ui.setup_dialog import SetupDialog

        dialog = SetupDialog(str(self.settings.value(SETTING_DB, "") or ""), self)
        dialog.database_chosen.connect(lambda name: self.settings.setValue(SETTING_DB, name))
        dialog.exec()
        ffmpeg.forget()  # it may have been installed just now

    def choose_database(self) -> None:
        start = str(paths.SANDBOXED if paths.SANDBOXED.exists() else paths.HOME)
        name, _ = QFileDialog.getOpenFileName(
            self, "Choose Mixxx Database", start, "Mixxx library (mixxxdb.sqlite *.sqlite)"
        )
        if name:
            self.open_database(Path(name))

    def open_database(self, path: Path) -> None:
        try:
            lib = Library(path)
        except AccessDenied:
            self._access_denied(path)
            return
        except NotMixxxDB as exc:
            QMessageBox.warning(self, "Not a Mixxx Library", str(exc))
            return
        if self.lib:
            self.lib.close()
        self.lib = lib
        self.settings.setValue(SETTING_DB, str(path))
        self.setWindowFilePath(str(path))
        self.status_path.setText(str(path))
        self.status_path.setToolTip(str(path))
        self.crate_id = 0
        self._check_guard()
        self.show_view(ALL)
        self.reload()
        self.apply_damage_notes(quiet=True)

    def _access_denied(self, path: Path) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Allow CR8TXXX to Read Mixxx's Library")
        box.setText(
            "macOS is keeping CR8TXXX out of Mixxx's library folder.\n\n"
            "Open System Settings › Privacy & Security › Full Disk Access, turn on CR8TXXX "
            "(add it with + if it isn't listed), then quit and reopen CR8TXXX."
        )
        box.setInformativeText(str(path))
        settings = box.addButton("Open System Settings", QMessageBox.ButtonRole.AcceptRole)
        choose = box.addButton("Choose Database…", QMessageBox.ButtonRole.ActionRole)
        retry = box.addButton("Try Again", QMessageBox.ButtonRole.ResetRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is settings:
            subprocess.run(["/usr/bin/open", paths.FULL_DISK_ACCESS_PANE], check=False)
        elif clicked is choose:
            self.choose_database()
        elif clicked is retry:
            self.open_database(path)

    # --- Read-only guard ---------------------------------------------------------------------

    def _check_guard(self) -> None:
        why = self.lib.why_read_only() if self.lib else "No library open."
        if why and self.notes_waiting:
            n = self.notes_waiting
            why += (f"  {n} damage note{'s' if n != 1 else ''} will be written to Mixxx's "
                    "Comment when it can be changed.")  # fmt: skip
        self.banner.setText("⚠  " + why if why else "")
        self.banner.setVisible(bool(why) and self.lib is not None)
        for act in self._write_actions:
            act.setEnabled(not why)
        for button in getattr(self, "_write_buttons", []):
            button.setEnabled(not why)
        if not why and self.notes_waiting and self.lib:
            self.apply_damage_notes()  # Mixxx was quit: write the notes that were waiting

    def _do(self, change: Callable[[], object], done: str = "") -> object:
        """Run one change, showing why if it can't be made; reload what's shown after."""
        try:
            result = change()
        except ReadOnly as exc:
            QMessageBox.information(self, "Can't Change the Library Now", str(exc))
            self._check_guard()
            return None
        except CrateError as exc:
            QMessageBox.information(self, "Crate", str(exc))
            return None
        self.reload()
        if done:
            self.toast(done)
        return result

    def toast(self, text: str) -> None:
        self.status_toast.setText(text)
        self._toast_timer.start(6000)

    # --- What's shown ------------------------------------------------------------------------

    def reload(self) -> None:
        if not self.lib:
            return
        all_crates = crates.list_crates(self.lib)
        self.crate_list.set_crates(all_crates)
        self.crate_count.setText(f"{len(all_crates)}")
        if self.crate_id and not any(c.id == self.crate_id for c in all_crates):
            self.crate_id = 0
        self._load_checks()
        self.show_view(self.view, keep_selection=True)
        self.show_crate(self.crate_id, keep_selection=True)
        self._set_count(HIDDEN, len(tracks.hidden(self.lib)))

    def _set_count(self, kind: str, n: int | None) -> None:
        label = dict((k, t) for k, t, _ in VIEWS)[kind]
        self.tab_buttons[kind].setText(label if n is None else f"{label}  {n:,}")

    def show_view(self, kind: str, keep_selection: bool = False) -> None:
        self.view = kind
        self.tab_buttons[kind].setChecked(True)
        pane = self.library
        if not self.lib:
            return
        selected = pane.selected_ids() if keep_selection else []
        self.scan_bar.setVisible(kind == SCAN)
        pane.set_forced({"check", "problem"} if kind == SCAN else set())
        if kind == SCAN:
            rows = self._problem_tracks()
            pane.set_tracks(rows, self._scan_empty())
            self._scan_summary_text()
            if selected:
                pane.select_ids(selected)
            self._status()
            return
        if kind == MISSING:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                rows = tracks.missing(self.lib)
            finally:
                QApplication.restoreOverrideCursor()
            pane.set_tracks(rows, EMPTY[MISSING])
        elif kind == HIDDEN:
            rows = tracks.hidden(self.lib)
            pane.set_tracks(rows, EMPTY[HIDDEN])
        else:
            rows = tracks.all_tracks(self.lib)
            pane.set_tracks(rows)
        self._set_count(kind, len(rows))
        if selected:
            pane.select_ids(selected)
        self._status()

    def show_crate(self, crate_id: int, keep_selection: bool = False) -> None:
        self.crate_id = crate_id
        pane = self.crate_pane
        if not self.lib or not crate_id:
            self.crate_name.setText("No crate selected")
            self.crate_summary.setText("")
            pane.show_message("Pick a crate", "Choose a crate above to see its tracks here, or "
                              "drag tracks from the library onto one.")  # fmt: skip
            return
        try:
            crate = crates.get(self.lib, crate_id)
        except CrateError:
            self.show_crate(0)
            return
        if self.crate_list.current_id() != crate_id:
            self.crate_list.select(crate_id)
        selected = pane.selected_ids() if keep_selection else []
        pane.set_tracks(tracks.in_crate(self.lib, crate_id), (
            "This crate is empty",
            "Drag tracks from the library into this pane or onto the crate, or drop music "
            "files and folders from Finder here.",
        ))  # fmt: skip
        self.crate_name.setText(crate.name + ("  🔒" if crate.locked else ""))
        total = clock(pane.model.total_seconds()) or "0:00"
        n = pane.model.rowCount()
        self.crate_summary.setText(f"{n:,} track{'s' if n != 1 else ''} · {total}")
        if selected:
            pane.select_ids(selected)

    def _filter(self, text: str) -> None:
        self.library.proxy.set_text(text)
        self._status()

    def _status(self) -> None:
        shown, total = self.library.proxy.rowCount(), self.library.model.rowCount()
        parts = [f"{shown:,} of {total:,} tracks" if shown != total else f"{total:,} tracks"]
        n_sel = len(self.library.selected_rows()) + len(self.crate_pane.selected_rows())
        if n_sel:
            parts.append(f"{n_sel:,} selected")
        self.status_counts.setText("   ·   ".join(parts) + "   ")

    def _focused_pane(self) -> TrackPane:
        """The pane whose selection an action works on: the one last clicked in."""
        if self.crate_pane.table.hasFocus() and self.crate_pane.selected_rows():
            return self.crate_pane
        if self.library.selected_rows():
            return self.library
        return self.crate_pane

    # --- Damaged file scan (step 2) ----------------------------------------------------------

    def _load_checks(self) -> None:
        """The scan's results, onto every table (red: damaged; amber: suspect)."""
        cache = Checks()
        try:
            self.checks = cache.all()
        finally:
            cache.close()
        statuses = {p: str(c.get("status") or "") for p, c in self.checks.items()}
        details = {p: _detail(c) for p, c in self.checks.items()
                   if c.get("status") not in ("ok", None)}  # fmt: skip
        for pane in (self.library, self.crate_pane):
            pane.model.set_checks(statuses, details)
        if self.lib:
            n = len(self._problem_tracks(bad_only=True))
            self._set_count(SCAN, n or None)
            self.tab_buttons[SCAN].setIcon(icons.icon("scan", theme.RED if n else theme.BLUE))

    def _status_of(self, t: tracks.Track) -> str:
        return str((self.checks.get(t.path) or {}).get("status") or "")

    def _problem_tracks(self, bad_only: bool = False) -> list[tracks.Track]:
        if not self.lib:
            return []
        wanted = BAD if bad_only else BAD | WARN
        return [t for t in tracks.all_tracks(self.lib) if self._status_of(t) in wanted]

    def _scan_empty(self) -> tuple[str, str]:
        if not self.checks:
            return EMPTY[SCAN]
        return ("No damaged files", "Every file checked so far is fine. Scan again after adding "
                "music: only new and changed files are checked.")  # fmt: skip

    def _scan_summary_text(self) -> None:
        if not self.lib or self.scan_worker:
            return
        counts: dict[str, int] = {}
        for t in tracks.all_tracks(self.lib):
            status = self._status_of(t) or "new"
            counts[status] = counts.get(status, 0) + 1
        bad = counts.get("damaged", 0) + counts.get("unreadable", 0)
        parts = [f"{bad:,} damaged" if bad else "none damaged"]
        for key, word in (("suspect", "suspect"), ("ok", "fine"),
                          (VERIFIED, "verified by listening"), ("unchecked", "need ffmpeg"),
                          ("new", "not checked yet")):  # fmt: skip
            if counts.get(key):
                parts.append(f"{counts[key]:,} {word}")
        self.scan_summary.setObjectName("ScanBad" if bad else "ScanSummary")
        self.scan_summary.style().unpolish(self.scan_summary)
        self.scan_summary.style().polish(self.scan_summary)
        self.scan_summary.setText(" · ".join(parts))
        self.scan_crate_btn.setVisible(bad > 0)
        self.scan_export_btn.setVisible(bool(self.checks))

    def start_scan(self, rescan: bool = False, show: bool = True) -> None:
        if not self.lib or self.scan_worker:
            return
        files = [t.path for t in tracks.all_tracks(self.lib) if not t.missing]
        if not files:
            return
        if rescan:
            sure = QMessageBox.question(
                self, "Rescan Everything",
                f"Check all {len(files):,} files again? This reads every file and can take "
                "a while.",
            )  # fmt: skip
            if sure != QMessageBox.StandardButton.Yes:
                return
        ffmpeg.forget()  # it may have been installed since
        self._scan_found = 0
        self._scan_started = time.monotonic()
        self.scan_worker = ScanWorker(files, rescan)
        self.scan_worker.progress.connect(self._scan_progress)
        self.scan_worker.checked.connect(self._scan_checked)
        self.scan_worker.done.connect(self._scan_done)
        for w in (self.scan_btn, self.rescan_btn, self.scan_crate_btn, self.scan_export_btn):
            w.hide()
        self.scan_progress.setRange(0, len(files))
        self.scan_progress.setValue(0)
        self.scan_progress.show()
        self.cancel_btn.show()
        self.scan_summary.setObjectName("ScanSummary")
        self.scan_summary.setText("Starting…")
        if show:
            self.show_view(SCAN)
        self.scan_worker.start()

    def cancel_scan(self) -> None:
        if self.scan_worker:
            self.scan_worker.cancel()
            self.scan_summary.setText("Stopping…")

    def _scan_progress(self, done: int, total: int, path: str) -> None:
        self.scan_progress.setValue(done)
        self.scan_progress.setFormat(f"{done:,} of {total:,}")
        left = ""
        spent = time.monotonic() - self._scan_started
        if done >= 10 and spent > 3 and done < total:
            secs = spent / done * (total - done)
            left = f" · about {max(1, round(secs / 60))} min left" if secs >= 60 else (
                f" · about {round(secs)} s left")  # fmt: skip
        found = f" · {self._scan_found} damaged so far" if self._scan_found else ""
        self.scan_summary.setText(f"{Path(path).name}{found}{left}" if path else "Finishing…")

    def _scan_checked(self, path: str, status: str) -> None:
        if status in BAD:
            self._scan_found += 1
            for pane in (self.library, self.crate_pane):  # red at once, everywhere
                pane.model.checks[path] = status
                pane.model.set_checks(pane.model.checks, pane.model.details)

    def _scan_done(self, counts: dict[str, object]) -> None:
        worker, self.scan_worker = self.scan_worker, None
        if worker:
            worker.wait()
        self.scan_progress.hide()
        self.cancel_btn.hide()
        self.scan_btn.show()
        self.rescan_btn.show()
        self.reload()
        noted = self.apply_damage_notes(quiet=True)
        bad = len(self._problem_tracks(bad_only=True))
        what = "Scan stopped" if counts.get("cancelled") else "Scan finished"
        msg = f"{what}: {counts.get('checked', 0):,} files checked, {bad:,} damaged in the library"
        if noted:
            msg += f"; noted {noted} in Mixxx's Comment"
        elif self.notes_waiting:
            msg += f"; {self.notes_waiting} notes waiting for Mixxx to close"
        self.toast(msg)
        if not counts.get("ffmpeg"):
            get = QMessageBox.question(
                self, "Only MP3s Were Checked",
                "ffmpeg isn't on this Mac, so only MP3 files could be checked. Download and "
                "install it now (into CR8TXXX's own folder, no password needed), then scan "
                "again to check the other formats?",
            )  # fmt: skip
            if get == QMessageBox.StandardButton.Yes:
                self.show_setup()

    def apply_damage_notes(self, quiet: bool = False) -> int:
        """Mixxx's Comment: the damage note on damaged tracks, taken off tracks found fine
        again. Waits (and says so in the banner) while Mixxx is running."""
        if not self.lib:
            return 0
        all_tracks = tracks.all_tracks(self.lib)
        damaged = [t.id for t in all_tracks if self._status_of(t) in BAD]
        fine = [t.id for t in all_tracks
                if self._status_of(t) in ("ok", VERIFIED)
                and tracks.noted(t.get("comment"))]  # fmt: skip
        to_note = [t for t in all_tracks
                   if t.id in set(damaged) and not tracks.noted(t.get("comment"))]  # fmt: skip
        if not to_note and not fine:
            self.notes_waiting = 0
            return 0
        if not self.lib.writable:
            self.notes_waiting = len(to_note) + len(fine)
            self._check_guard()
            return 0
        added, cleared = tracks.note_damage(self.lib, damaged, fine)
        self.notes_waiting = 0
        self._check_guard()
        self.reload()
        if not quiet and (added or cleared):
            self.toast(f"Damage notes written to Mixxx's Comment: {added} added, {cleared} cleared")
        return added

    def damaged_to_crate(self) -> None:
        ids = [t.id for t in self._problem_tracks(bad_only=True)]
        if not self.lib or not ids:
            return

        def put() -> int:
            assert self.lib
            cid = crates.find_or_create(self.lib, DAMAGED_CRATE)
            crates.add_tracks(self.lib, cid, ids)
            return cid

        cid = self._do(put, f"{len(ids)} damaged tracks are in the crate “{DAMAGED_CRATE}”")
        if isinstance(cid, int):
            self.show_crate(cid)

    def export_scan(self) -> None:
        rows = self._problem_tracks()
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Damaged Files", str(paths.HOME / "Damaged Files.csv"), "CSV (*.csv)"
        )
        if not dest:
            return
        with open(dest, "w", newline="", encoding="utf-8") as f:
            out = csv.writer(f)
            out.writerow(["Status", "Artist", "Title", "Album", "Problem", "Location"])
            for t in rows:
                check = self.checks.get(t.path) or {}
                out.writerow([CHECK_WORDS.get(self._status_of(t), ""), t.get("artist") or "",
                              t.get("title") or "", t.get("album") or "",
                              checker.describe(check), t.path])  # fmt: skip
        self.toast(f"Exported {len(rows)} tracks to {dest}")

    # --- Verified Undamaged by Listening ------------------------------------------------------

    def verify_tracks(self, chosen: list[tracks.Track]) -> None:
        """Listened to and fine: no longer marked damaged, and the damage note comes out of
        Mixxx's Comment (now, or when Mixxx quits)."""
        flagged = [t for t in chosen if self._status_of(t) in BAD | WARN]
        if not flagged:
            return
        n = len(flagged)
        names = "\n".join(f"  • {_name(t)}" for t in flagged[:10])
        more = f"\n  … and {n - 10} more" if n > 10 else ""
        sure = QMessageBox.question(
            self, "Verified Undamaged by Listening",
            f"Are you sure? You listened to {'this track' if n == 1 else f'these {n} tracks'} "
            f"and {'it plays' if n == 1 else 'they play'} correctly.\n\n{names}{more}\n\n"
            f"{'It' if n == 1 else 'They'}'ll no longer be marked damaged, and the damage note "
            "will be removed from Mixxx's Comment where it's still there.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )  # fmt: skip
        if sure != QMessageBox.StandardButton.Ok:
            return
        cache = Checks()
        done, gone = 0, 0
        try:
            for t in flagged:
                try:
                    cache.verify(t.path, dict(self.checks.get(t.path) or {}))
                    done += 1
                except OSError:  # the file isn't there to vouch for
                    gone += 1
        finally:
            cache.close()
        self.reload()
        self.apply_damage_notes(quiet=True)
        msg = f"Marked {done} track{'s' if done != 1 else ''} as verified undamaged by listening"
        if self.notes_waiting:
            msg += "; the Comment notes come out when Mixxx quits"
        if gone:
            msg += f" ({gone} skipped: the file is missing)"
        self.toast(msg)

    def unverify_tracks(self, chosen: list[tracks.Track]) -> None:
        """Take the mark off: the files are checked again now (only they are read)."""
        cache = Checks()
        try:
            for t in chosen:
                cache.unverify(t.path)
        finally:
            cache.close()
        self.reload()
        self.toast(f"Removed the verified mark from {len(chosen)} track(s); checking them again")
        self.start_scan(show=False)

    # --- Find New Songs ------------------------------------------------------------------------

    def find_new_songs(self) -> None:
        """Mixxx's music folders, looked through for songs not in the library yet."""
        if not self.lib or getattr(self, "folder_scan", None):
            return
        roots = tracks.roots(self.lib)
        if not roots:
            QMessageBox.information(
                self, "No Music Folders",
                "Mixxx has no music folders yet. Add one in Mixxx › Preferences › Library, "
                "or use Add Folder here.",
            )  # fmt: skip
            return
        self.folder_scan = FolderScan(roots, tracks.known_locations(self.lib))
        dialog = QProgressDialog("Looking for new songs…", "Cancel", 0, 0, self)
        dialog.setWindowTitle("Find New Songs")
        dialog.setMinimumDuration(400)
        dialog.setMinimumWidth(theme.px(460))
        dialog.canceled.connect(self.folder_scan.cancel)
        self._folder_dialog = dialog

        def where(folder: str) -> None:
            short = folder if len(folder) < 70 else "…" + folder[-68:]
            dialog.setLabelText(f"Looking for new songs…\n{short}")

        self.folder_scan.progress.connect(where)
        self.folder_scan.done.connect(self._new_songs_found)
        self.folder_scan.start()

    def _new_songs_found(self, found: list[str], unreadable: list[str], cancelled: bool) -> None:
        worker, self.folder_scan = self.folder_scan, None
        if worker:
            worker.wait()
        self._folder_dialog.reset()
        self._folder_dialog.close()
        if cancelled:
            self.toast("Find New Songs stopped")
            return
        skipped = ""
        if unreadable:
            skipped = ("\n\nThese music folders couldn't be read (a drive not connected?):\n"
                       + "\n".join(f"  • {f}" for f in unreadable))  # fmt: skip
        if not found:
            n = len(tracks.roots(self.lib)) if self.lib else 0
            QMessageBox.information(
                self, "No New Songs",
                f"No new songs. Your {n} music folder{'s' if n != 1 else ''} "
                f"{'were' if n != 1 else 'was'} checked.{skipped}",
            )  # fmt: skip
            return
        if not self._confirm_new_songs(found, skipped):
            return
        result = self.add_paths(0, found)
        if result and result.added:
            n = len(result.added)
            again = QMessageBox.question(
                self, "Check for Damage?",
                f"Check the {n} new song{'s' if n != 1 else ''} for damage now?",
            )  # fmt: skip
            if again == QMessageBox.StandardButton.Yes:
                self.start_scan()

    def _confirm_new_songs(self, found: list[str], skipped: str) -> bool:
        """The new songs, listed: Add to Library or Cancel."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Find New Songs")
        col = QVBoxLayout(dialog)
        n = len(found)
        head = QLabel(f"Found {n:,} new song{'s' if n != 1 else ''} in your music folders. "
                      "They'll be added with their tags; Mixxx analyzes BPM and key itself."
                      + skipped)  # fmt: skip
        head.setWordWrap(True)
        col.addWidget(head)
        listing = QListWidget()
        for path in found:
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            listing.addItem(item)
        col.addWidget(listing, 1)
        buttons = QDialogButtonBox()
        buttons.addButton("Add to Library", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        theme.fit_to_screen(dialog, 0.4, 0.5, 520, 360)
        return dialog.exec() == QDialog.DialogCode.Accepted

    # --- Context menus -----------------------------------------------------------------------

    def track_menu(self, pane: TrackPane, pos: QPoint) -> None:
        if not self.lib or not pane.selected_ids():
            return
        ids = pane.selected_ids()
        chosen = pane.selected_tracks()
        writable = self.lib.writable
        menu = QMenu(self)
        menu.addAction("Edit Details…", lambda: self.edit_tracks(chosen)).setEnabled(writable)
        add = menu.addMenu("Add to Crate")
        add.setEnabled(writable)
        for c in crates.list_crates(self.lib):
            act = add.addAction(c.name + ("  🔒" if c.locked else ""))
            act.setEnabled(not c.locked)
            act.triggered.connect(lambda _c=False, cid=c.id: self.add_to_crate(cid, ids))
        add.addSeparator()
        add.addAction("New Crate…").triggered.connect(lambda: self.new_crate(ids))
        if pane is self.crate_pane and self.crate_id:
            act = menu.addAction("Remove from This Crate")
            act.setEnabled(writable)
            act.triggered.connect(lambda: self.remove_from_crate(self.crate_id, ids))
        menu.addSeparator()
        menu.addAction("Reveal in Finder", lambda: self.reveal(chosen))
        flagged = [t for t in chosen if self._status_of(t) in BAD | WARN]
        verified = [t for t in chosen if self._status_of(t) == VERIFIED]
        if flagged or verified:
            menu.addSeparator()
        if flagged:
            menu.addAction("Mark as Verified Undamaged by Listening…",
                           lambda: self.verify_tracks(flagged))  # fmt: skip
        if verified:
            menu.addAction("Remove Verified Mark", lambda: self.unverify_tracks(verified))
        menu.addSeparator()
        if pane is self.library and self.view == HIDDEN:
            act = menu.addAction("Show in Library Again")
            act.setEnabled(writable)
            act.triggered.connect(lambda: self._do(lambda: tracks.unhide(self.lib, ids)))
        else:
            act = menu.addAction("Hide from Library")
            act.setEnabled(writable)
            act.triggered.connect(lambda: self.hide(ids))
        act = menu.addAction("Purge from Library…")
        act.setEnabled(writable)
        act.triggered.connect(lambda: self.purge(ids))
        if pane is self.library and self.view == MISSING:
            menu.addSeparator()
            menu.addAction(self.a_relocate)
        menu.exec(pane.table.viewport().mapToGlobal(pos))

    def column_menu(self, pane: TrackPane, pos: QPoint) -> None:
        menu = QMenu(self)
        for i, heading in enumerate(HEADINGS):
            if not heading:
                continue
            act = menu.addAction(heading)
            act.setCheckable(True)
            act.setChecked(KEYS[i] not in pane.chosen_hidden)
            act.toggled.connect(lambda on, col=i, p=pane: self._show_column(p, col, on))
        menu.addSeparator()
        fit = menu.addAction("Fit Columns to Pane")
        fit.triggered.connect(pane.fit_again)
        menu.exec(pane.table.horizontalHeader().mapToGlobal(pos))

    def _show_column(self, pane: TrackPane, column: int, on: bool) -> None:
        pane.set_column_shown(KEYS[column], on)

    def crate_menu(self, crate_id: int, where: QPoint) -> None:
        if not self.lib:
            return
        writable = self.lib.writable
        menu = QMenu(self)
        if not crate_id:
            menu.addAction(self.a_new_crate)
            menu.addAction(self.a_import)
            menu.exec(where)
            return
        c = crates.get(self.lib, crate_id)
        for text, slot in (("Rename…", lambda: self.rename_crate(crate_id)),
                           ("Delete…", lambda: self.delete_crate(crate_id))):  # fmt: skip
            act = menu.addAction(text)
            act.setEnabled(writable and not c.locked)
            act.triggered.connect(slot)
        menu.addSeparator()
        for text, on, setter in (
            ("Locked", c.locked, crates.set_locked),
            ("Show in Mixxx's Sidebar", c.show, crates.set_show),
            ("Auto DJ Source", c.autodj, crates.set_autodj),
        ):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(on)
            act.setEnabled(writable)
            act.toggled.connect(
                lambda value, fn=setter: self._do(lambda: fn(self.lib, crate_id, value))
            )
        menu.addSeparator()
        menu.addAction("Export as M3U…").triggered.connect(lambda: self.export_m3u(crate_id))
        menu.exec(where)

    # --- Crates ------------------------------------------------------------------------------

    def new_crate(self, ids: list[int] | None = None) -> None:
        if not self.lib:
            return
        name, ok = QInputDialog.getText(self, "New Crate", "Name:")
        if not ok or not name.strip():
            return

        def make() -> int:
            assert self.lib
            cid = crates.create(self.lib, name)
            if ids:
                crates.add_tracks(self.lib, cid, ids)
            return cid

        cid = self._do(make, f"Made crate “{name.strip()}”")
        if isinstance(cid, int):
            self.show_crate(cid)

    def rename_crate(self, crate_id: int) -> None:
        assert self.lib
        old = crates.get(self.lib, crate_id).name
        name, ok = QInputDialog.getText(self, "Rename Crate", "Name:", text=old)
        if ok and name.strip() and name.strip() != old:
            self._do(lambda: crates.rename(self.lib, crate_id, name), "Crate renamed")

    def delete_crate(self, crate_id: int) -> None:
        assert self.lib
        c = crates.get(self.lib, crate_id)
        sure = QMessageBox.question(
            self, "Delete Crate",
            f"Delete the crate “{c.name}”? Its {c.tracks} tracks stay in the library.",
        )  # fmt: skip
        if sure == QMessageBox.StandardButton.Yes:
            self._do(lambda: crates.delete(self.lib, crate_id), f"Deleted “{c.name}”")

    def add_to_crate(self, crate_id: int, ids: list[int]) -> None:
        if not self.lib or not ids or not crate_id:
            return
        name = crates.get(self.lib, crate_id).name
        n = self._do(lambda: crates.add_tracks(self.lib, crate_id, ids))
        if isinstance(n, int):
            already = len(ids) - n
            extra = f" ({already} already there)" if already else ""
            self.toast(f"Added {n} to “{name}”{extra}")

    def remove_from_crate(self, crate_id: int, ids: list[int]) -> None:
        self._do(lambda: crates.remove_tracks(self.lib, crate_id, ids),
                 f"Removed {len(ids)} from the crate")  # fmt: skip

    def export_m3u(self, crate_id: int) -> None:
        assert self.lib
        c = crates.get(self.lib, crate_id)
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export Crate", str(paths.HOME / f"{c.name}.m3u"), "Playlist (*.m3u *.m3u8)"
        )
        if dest:
            n = crates.export_m3u(self.lib, crate_id, dest)
            self.toast(f"Exported {n} tracks to {dest}")

    def import_m3u(self) -> None:
        src, _ = QFileDialog.getOpenFileName(
            self, "Import Playlist as Crate", str(paths.HOME), "Playlist (*.m3u *.m3u8)"
        )
        if not src:
            return
        name, ok = QInputDialog.getText(self, "New Crate", "Name:", text=Path(src).stem)
        if not ok or not name.strip():
            return
        got = self._do(lambda: crates.import_m3u(self.lib, src, name))
        if isinstance(got, tuple):
            cid, n, gone = got
            self.show_crate(cid)
            msg = f"Crate “{name}” made with {n} tracks."
            if gone:
                msg += (
                    f"\n\n{len(gone)} files in the playlist weren't found:\n"
                    + "\n".join(gone[:15])
                    + ("\n…" if len(gone) > 15 else "")
                )
                QMessageBox.information(self, "Imported", msg)
            else:
                self.toast(msg)

    # --- Adding tracks -----------------------------------------------------------------------

    def add_files_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(tracks.AUDIO))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add Music Files", str(paths.HOME / "Music"), f"Music ({exts})"
        )
        if files:
            self.add_paths(0, files)

    def add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add Music Folder", str(paths.HOME))
        if folder:
            self.add_paths(0, [folder])

    def add_paths(self, crate_id: int, dropped: list[str]) -> tracks.AddResult | None:
        """Files and folders (dragged in or chosen) into the library, and into a crate."""
        if not self.lib:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files: list[str] = []
            for p in dropped:
                if os.path.isdir(p):
                    files += tracks.audio_files(p)
                elif Path(p).suffix.lower() in tracks.AUDIO:
                    files.append(p)
        finally:
            QApplication.restoreOverrideCursor()
        if not files:
            QMessageBox.information(self, "Nothing to Add", "No music files were found there.")
            return
        outside = tracks.outside_roots(self.lib, files)
        if outside:
            sure = QMessageBox.question(
                self, "Outside Mixxx's Music Folders",
                f"{len(outside):,} of these {len(files):,} files are outside the folders Mixxx "
                "has been given (Mixxx › Preferences › Library). Mixxx from mixxx.org can only "
                "open files in those folders, so these may not load in Mixxx.\n\nAdd them anyway?",
            )  # fmt: skip
            if sure != QMessageBox.StandardButton.Yes:
                return

        def add() -> tracks.AddResult:
            assert self.lib
            result = tracks.add_files(self.lib, files)
            if crate_id:
                wanted = {os.path.abspath(f) for f in files}
                ids = [t.id for t in tracks.all_tracks(self.lib) if t.path in wanted]
                crates.add_tracks(self.lib, crate_id, ids)
            return result

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self._do(add)
        finally:
            QApplication.restoreOverrideCursor()
        if isinstance(result, tracks.AddResult):
            parts = [f"Added {len(result.added):,} tracks"]
            if result.restored:
                parts.append(f"{len(result.restored):,} brought back from hidden")
            if result.already:
                parts.append(f"{len(result.already):,} already in the library")
            if crate_id:
                parts.append(f"all put in “{crates.get(self.lib, crate_id).name}”")
            self.toast(" · ".join(parts))
            return result
        return None

    # --- Editing, hiding, purging, relocating -------------------------------------------------

    def edit_selected(self) -> None:
        self.edit_tracks(self._focused_pane().selected_tracks())

    def edit_tracks(self, chosen: list[tracks.Track]) -> None:
        if not self.lib or not chosen:
            return
        dialog = EditDialog(chosen, self)
        if dialog.exec():
            changes = dialog.changes()
            if changes:
                ids = [t.id for t in chosen]
                self._do(lambda: tracks.update_metadata(self.lib, ids, changes),
                         f"Saved changes to {len(ids)} track(s)")  # fmt: skip

    def hide_selected(self) -> None:
        self.hide(self._focused_pane().selected_ids())

    def hide(self, ids: list[int]) -> None:
        if ids:
            self._do(lambda: tracks.hide(self.lib, ids),
                     f"Hid {len(ids)} track(s); see Hidden to bring them back")  # fmt: skip

    def purge(self, ids: list[int]) -> None:
        sure = QMessageBox.warning(
            self, "Purge from Library",
            f"Forget {len(ids)} track(s) completely? Their cues, beat grids, analysis and "
            "crate places are deleted from Mixxx's library. The files themselves are not "
            "touched.\n\nA backup of the library is kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )  # fmt: skip
        if sure == QMessageBox.StandardButton.Yes:
            self._do(lambda: tracks.purge(self.lib, ids), f"Purged {len(ids)} track(s)")

    def relocate(self) -> None:
        if not self.lib:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lost = tracks.missing(self.lib)
        finally:
            QApplication.restoreOverrideCursor()
        if not lost:
            QMessageBox.information(self, "Nothing Missing", "Every track's file is in place.")
            return
        dialog = RelocateDialog(lost, self)
        if dialog.exec():
            moves = dialog.chosen()
            got = self._do(lambda: tracks.apply_moves(self.lib, moves))
            if isinstance(got, tuple):
                done, clashes = got
                msg = f"Relocated {done:,} tracks."
                if clashes:
                    msg += f" {len(clashes)} skipped: another track already uses that file."
                QMessageBox.information(self, "Relocated", msg)

    def reveal_selected(self) -> None:
        self.reveal(self._focused_pane().selected_tracks())

    def reveal(self, chosen: list[tracks.Track]) -> None:
        for t in [t for t in chosen if not t.missing][:20]:
            subprocess.run(["/usr/bin/open", "-R", t.path], check=False)

    def show_backups(self) -> None:
        subprocess.run(["/usr/bin/open", str(paths.backups_dir())], check=False)


def theme_size(n: float) -> QSize:
    return QSize(theme.px(n), theme.px(n))


def _name(t: tracks.Track) -> str:
    artist, title = t.get("artist") or "", t.get("title") or Path(t.path).name
    return f"{artist} – {title}" if artist else str(title)


def _detail(check: dict[str, object]) -> str:
    """What the Check column's tooltip and the Problem column say."""
    if check.get("status") == VERIFIED:
        when = str(check.get("verified_at") or "")[:10]
        was = check.get("was") or {}
        found = checker.describe(was) if isinstance(was, dict) and was.get("status") else ""
        return f"verified undamaged by listening on {when}" + (
            f" (the scan had found: {found})" if found else "")  # fmt: skip
    return checker.describe(check)
