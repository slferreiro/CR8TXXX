# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
# PyInstaller recipe for CR8TXXX.app (Apple silicon). Build with `make dist` from the
# project folder.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from cr8txxx import __version__  # noqa: E402

# ffmpeg inside the app is optional (`make ffmpeg` builds one): without it, first-run setup
# downloads it on the Mac CR8TXXX is installed on, with the person's OK.
FFMPEG = Path(os.environ.get("CR8TXXX_FFMPEG", "/nonexistent"))
BUNDLE_FFMPEG = all((FFMPEG / tool).is_file() for tool in ("ffmpeg", "ffprobe"))
print("Bundling ffmpeg from", FFMPEG if BUNDLE_FFMPEG else "nowhere: setup downloads it")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[(str(FFMPEG / t), "ffmpeg-bin") for t in ("ffmpeg", "ffprobe")] if BUNDLE_FFMPEG
    else [],
    datas=[(str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
           (str(ROOT / "licenses"), "licenses")],
    hiddenimports=[*collect_submodules("cr8txxx"), *collect_submodules("tinytag"),
                   "PySide6.QtSvg"],
    excludes=["tkinter", "pytest", "mypy", "ruff", "IPython",
              # Qt parts CR8TXXX doesn't use
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.QtMultimedia", "PySide6.Qt3DCore",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CR8TXXX",
    console=False,
    target_arch="arm64",
    codesign_identity=None,  # packaging/sign.sh signs the finished app
)
coll = COLLECT(exe, a.binaries, a.datas, name="CR8TXXX")
app = BUNDLE(
    coll,
    name="CR8TXXX.app",
    icon=str(ROOT / "packaging" / "assets" / "CR8TXXX.icns"),
    bundle_identifier="com.cr8txxx.app",
    version=__version__,
    info_plist={
        "CFBundleName": "CR8TXXX",  # the menu bar's app name
        "CFBundleDisplayName": "CR8TXXX",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 Sean Ferreiro · GPL-3.0-or-later",
    },
)
