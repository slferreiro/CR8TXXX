# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""First-run setup: the ffmpeg download (from a local zip: no network in tests) and the
setup window's rows."""

import os
import shutil
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import make_db  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cr8txxx import paths  # noqa: E402
from cr8txxx.scan import ffmpeg, ffmpeg_download  # noqa: E402
from cr8txxx.ui import setup_dialog  # noqa: E402

REAL = ffmpeg.look(list(ffmpeg.PLACES))
needs_ffmpeg = pytest.mark.skipif(REAL is None, reason="no ffmpeg on this Mac to package")


def zipped(tmp: Path, name: str, src: str) -> str:
    z = tmp / f"{name}.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(src, name)
    return z.as_uri()  # curl reads file:// like https://


@needs_ffmpeg
def test_install_from_zips(tmp_path: Path) -> None:
    assert REAL
    urls = {"ffmpeg": zipped(tmp_path, "ffmpeg", REAL.ffmpeg),
            "ffprobe": zipped(tmp_path, "ffprobe", REAL.ffprobe)}  # fmt: skip
    seen: list[str] = []
    tool = ffmpeg_download.install(urls, lambda name, size: seen.append(name))
    own = paths.support_dir() / ffmpeg.USER_FOLDER
    assert tool.ffmpeg == str(own / "ffmpeg") and os.access(tool.ffprobe, os.X_OK)
    assert "ffmpeg" in seen and "ffprobe" in seen
    ffmpeg.forget()
    assert ffmpeg.locate() is not None  # found in CR8TXXX's folder from now on


def test_bad_download_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "x.zip"
    junk.write_text("not a zip")
    with pytest.raises(ffmpeg_download.DownloadError, match="wasn't a zip"):
        ffmpeg_download.install({"ffmpeg": junk.as_uri()})
    with pytest.raises(ffmpeg_download.DownloadError, match="Couldn't download"):
        ffmpeg_download.install({"ffmpeg": (tmp_path / "missing.zip").as_uri()})


def test_setup_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    QApplication.instance() or QApplication([])
    db = make_db(tmp_path)
    monkeypatch.setattr(ffmpeg, "locate", lambda folder="": None)
    d = setup_dialog.SetupDialog(str(db))
    assert d.library_state == setup_dialog.READY
    assert d.ffmpeg_state == setup_dialog.OPTIONAL
    d.close()
    monkeypatch.setattr(paths, "candidates", lambda: [tmp_path / "nowhere" / "mixxxdb.sqlite"])
    d = setup_dialog.SetupDialog(str(tmp_path / "nowhere.sqlite"))  # no Mixxx on this "Mac"
    assert d.library_state == setup_dialog.NEEDED


@needs_ffmpeg
def test_setup_download_button(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    QApplication.instance() or QApplication([])
    assert REAL
    urls = {"ffmpeg": zipped(tmp_path, "ffmpeg", REAL.ffmpeg),
            "ffprobe": zipped(tmp_path, "ffprobe", REAL.ffprobe)}  # fmt: skip
    real_locate = ffmpeg.locate
    own = str(paths.support_dir() / ffmpeg.USER_FOLDER)
    monkeypatch.setattr(ffmpeg, "locate", lambda folder="": ffmpeg.look([own]))
    d = setup_dialog.SetupDialog(str(make_db(tmp_path)), urls=urls)
    assert d.ffmpeg_state == setup_dialog.OPTIONAL
    d.start_download()
    d.download.wait(60000)
    QApplication.processEvents()
    QApplication.processEvents()
    assert d.ffmpeg_state == setup_dialog.READY
    assert shutil.which("ffmpeg", path=own)
    monkeypatch.setattr(ffmpeg, "locate", real_locate)
