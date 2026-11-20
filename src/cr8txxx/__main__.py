# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""CR8TXXX: run with ``uv run python -m cr8txxx`` (or open CR8TXXX.app)."""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cr8txxx import __version__, paths
from cr8txxx.ui import icons
from cr8txxx.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(paths.APP_NAME)
    app.setWindowIcon(icons.app_icon())
    window = MainWindow()  # applies the theme at the saved text size
    window.show()
    QTimer.singleShot(0, window.open_first)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
