# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Builds packaging/assets/CR8TXXX.icns (and a 1024 px PNG) from the icon CR8TXXX draws
itself (cr8txxx.ui.icons.draw_app_icon). Run with ``make icon``."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cr8txxx.ui.icons import draw_app_icon  # noqa: E402

ASSETS = Path(__file__).parent / "assets"


def main() -> int:
    QApplication.instance() or QApplication(sys.argv)
    ASSETS.mkdir(exist_ok=True)
    draw_app_icon(1024).save(str(ASSETS / "CR8TXXX.png"))
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "CR8TXXX.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            draw_app_icon(size).save(str(iconset / f"icon_{size}x{size}.png"))
            draw_app_icon(size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))
        if not shutil.which("iconutil"):
            print("iconutil not found (it comes with macOS)")
            return 1
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o",
                        str(ASSETS / "CR8TXXX.icns")], check=True)  # fmt: skip
    print(ASSETS / "CR8TXXX.icns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
