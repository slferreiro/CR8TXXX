# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Getting ffmpeg onto a Mac that doesn't have it (first-run setup, with the person's OK):
ffmpeg and ffprobe for Apple silicon, prebuilt and self-contained (Martin Riedl's macOS
builds, ffmpeg.martin-riedl.de), into CR8TXXX's own folder
(~/Library/Application Support/CR8TXXX/ffmpeg-bin). No admin password; nothing else on the
Mac is touched, and deleting that folder undoes it.

Downloads use macOS's own curl (the system's certificates), a file at a time, into a
temporary file that's only moved into place once it has been unpacked and runs."""

import os
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

from cr8txxx import paths
from cr8txxx.scan import ffmpeg

BASE = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release"
URLS = {"ffmpeg": f"{BASE}/ffmpeg.zip", "ffprobe": f"{BASE}/ffprobe.zip"}
CURL = "/usr/bin/curl"


class DownloadError(Exception):
    """The download or install didn't work (the message says why, for a person)."""


def folder() -> Path:
    return paths.support_dir() / ffmpeg.USER_FOLDER


def install(
    urls: dict[str, str] | None = None,
    progress: Callable[[str, int], None] | None = None,
    stop: Callable[[], bool] | None = None,
) -> ffmpeg.Tool:
    """Download ffmpeg and ffprobe and put them in CR8TXXX's folder; the tool that now
    works. ``progress(name, bytes so far)`` while each downloads."""
    urls = urls or URLS
    dest = folder()
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.support_dir()) as tmp:
        for name, url in urls.items():
            archive = Path(tmp) / f"{name}.zip"
            _download(url, archive, name, progress, stop)
            binary = _unpack(archive, name, Path(tmp))
            os.chmod(binary, os.stat(binary).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            shutil.move(str(binary), dest / name)
    ffmpeg.forget()
    tool = ffmpeg.look([str(dest)])
    if tool is None:
        raise DownloadError("ffmpeg was downloaded but doesn't run on this Mac.")
    return tool


def _download(url: str, out: Path, name: str, progress: Callable[[str, int], None] | None,
              stop: Callable[[], bool] | None) -> None:  # fmt: skip
    job = subprocess.Popen(
        [CURL, "--fail", "--location", "--silent", "--show-error", "--retry", "2",
         "--max-time", "900", "--output", str(out), url],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    while job.poll() is None:
        if stop and stop():
            job.terminate()
            job.wait()
            raise DownloadError("The download was cancelled.")
        if progress:
            progress(name, out.stat().st_size if out.exists() else 0)
        time.sleep(0.2)
    if job.returncode != 0:
        why = (job.stderr.read().decode(errors="replace").strip() if job.stderr else "")[:300]
        raise DownloadError(f"Couldn't download {name} (is the Mac online?). {why}".strip())
    if progress:
        progress(name, out.stat().st_size)


def _unpack(archive: Path, name: str, where: Path) -> Path:
    try:
        with zipfile.ZipFile(archive) as z:
            members = [m for m in z.namelist() if Path(m).name == name and not m.endswith("/")]
            if not members:
                raise DownloadError(f"The {name} download didn't contain {name}.")
            target = where / f"{name}-unpacked"
            target.write_bytes(z.read(members[0]))
            return target
    except zipfile.BadZipFile as exc:
        raise DownloadError(f"The {name} download wasn't a zip file.") from exc
