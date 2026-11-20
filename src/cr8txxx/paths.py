# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Where things are. Nothing here is specific to one Mac: the Mixxx database is looked for
in the places Mixxx itself uses, and every music file's path comes from that database."""

from pathlib import Path

APP_NAME = "CR8TXXX"
DB_NAME = "mixxxdb.sqlite"

HOME = Path.home()

# Mixxx from mixxx.org / the App Store is sandboxed (2.4+): its settings live in its container.
SANDBOXED = HOME / "Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx"
# Builds without the sandbox (Homebrew, older versions, self-built)
UNSANDBOXED = HOME / "Library/Application Support/Mixxx"

FULL_DISK_ACCESS_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


def candidates() -> list[Path]:
    """Where a Mixxx database may be, in the order to try."""
    return [SANDBOXED / DB_NAME, UNSANDBOXED / DB_NAME]


def support_dir() -> Path:
    """CR8TXXX's own folder (backups, the damaged-file scan's results)."""
    path = HOME / "Library/Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir() -> Path:
    path = support_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path
