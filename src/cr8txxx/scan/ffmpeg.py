# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""ffmpeg and ffprobe, for checking formats other than MP3. Taken from FMM (FMM 0.91.0,
src/fmm/services/ffmpeg.py: Tool, look, locate).

Where it's looked for, in order: inside CR8TXXX.app (when a build bundles one:
packaging/build_ffmpeg.sh), CR8TXXX's own folder (where first-run setup downloads it:
scan/ffmpeg_download.py), Homebrew's folders, then the PATH (an app opened from Finder gets a
short PATH, so Homebrew's folders are always tried)."""

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PLACES = ("/opt/homebrew/bin", "/usr/local/bin")
BUNDLED = "ffmpeg-bin"  # the folder inside CR8TXXX.app (PyInstaller's sys._MEIPASS)
USER_FOLDER = "ffmpeg-bin"  # in ~/Library/Application Support/CR8TXXX (first-run setup)


def bundled() -> list[str]:
    """CR8TXXX.app's own ffmpeg folder, when running as the app."""
    base = getattr(sys, "_MEIPASS", None)
    return [str(Path(base) / BUNDLED)] if base else []


@dataclass(frozen=True)
class Tool:
    ffmpeg: str
    ffprobe: str
    version: str


_found: dict[str, Tool | None] = {}
_lock = threading.Lock()


def _run(args: list[str], timeout: float = 15) -> str:
    """A command's output (never through a shell); "" when it can't run."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def look(places: list[str]) -> Tool | None:
    """The first of these folders with a working ffmpeg and ffprobe."""
    for place in places:
        ffmpeg, ffprobe = Path(place) / "ffmpeg", Path(place) / "ffprobe"
        if not (os.access(ffmpeg, os.X_OK) and os.access(ffprobe, os.X_OK)):
            continue
        version = _run([str(ffmpeg), "-hide_banner", "-version"]).split("\n", 1)[0]
        if not version.startswith("ffmpeg version"):
            continue
        return Tool(str(ffmpeg), str(ffprobe), version.split()[2])
    return None


def locate(folder: str = "") -> Tool | None:
    """ffmpeg and ffprobe in ``folder``, else Homebrew's places, else the PATH (looked for
    once, until ``forget``)."""
    with _lock:
        if folder in _found:
            return _found[folder]
    from cr8txxx import paths

    own = str(paths.support_dir() / USER_FOLDER)
    tool = look([folder] if folder else [*bundled(), own, *PLACES, *os.get_exec_path()])
    with _lock:
        _found[folder] = tool
    return tool


def forget() -> None:
    """Look again next time (ffmpeg was installed meanwhile)."""
    with _lock:
        _found.clear()


def install_hint() -> str:
    return "brew install ffmpeg" if shutil.which("brew") or Path(PLACES[0], "brew").exists() else (
        "install Homebrew (brew.sh), then: brew install ffmpeg")  # fmt: skip
