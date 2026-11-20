# Third-party notices

CR8TXXX is free software under the GNU General Public License, version 3 or (at your
option) any later version: see [LICENSE](LICENSE). It is built on, and the macOS app
(CR8TXXX.app) contains, the following software, each under its own licence. Their full
licence texts are in [licenses/](licenses/) (and, in the app, in
`CR8TXXX.app/Contents/Resources/licenses`).

| Component | Used for | Licence | Text |
|---|---|---|---|
| [Qt](https://www.qt.io) 6 and [Qt for Python (PySide6, Shiboken6)](https://doc.qt.io/qtforpython-6/) | the window, tables and drawing | LGPL-3.0 (PySide6: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only) | [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt), with [LICENSE](LICENSE) |
| [Python](https://www.python.org) 3.12 | runs CR8TXXX (inside the app) | PSF License Agreement | [licenses/Python-PSF.txt](licenses/Python-PSF.txt) |
| [tinytag](https://github.com/tinytag/tinytag) | reading music files' tags when adding songs | MIT | [licenses/tinytag-MIT.txt](licenses/tinytag-MIT.txt) |

The Qt and PySide6 libraries are separate, replaceable libraries inside the app
(`CR8TXXX.app/Contents/Frameworks/PySide6`); their source code is available from
[qt.io](https://download.qt.io/official_releases/) and
[code.qt.io](https://code.qt.io/cgit/pyside/pyside-setup.git/).

## ffmpeg

The damaged-file scan uses [ffmpeg](https://ffmpeg.org) to check formats other than MP3.
CR8TXXX.app does not include it. On first run, *Set Up CR8TXXX* offers to download a
prebuilt ffmpeg for Apple silicon ([Martin Riedl's macOS builds](https://ffmpeg.martin-riedl.de),
GPL) into `~/Library/Application Support/CR8TXXX/ffmpeg-bin`, where it runs as a separate
program; or it uses an ffmpeg already installed (for example `brew install ffmpeg`).
`make ffmpeg` builds an audio-only ffmpeg under the LGPL-2.1-or-later
(`packaging/build_ffmpeg.sh`) for builds that bundle it; ffmpeg's source code is at
[ffmpeg.org](https://ffmpeg.org/download.html).

## Code from FMM

The music-file checker (`src/cr8txxx/scan/checker.py`, `src/cr8txxx/scan/ffmpeg.py`) comes
from FMM by the same author, where it is MIT-licensed; here it is part of CR8TXXX under the
GPL-3.0-or-later.

## Not included

CR8TXXX's dark theme uses the colour palette of the TwrRcrds Mixxx skin. No files, images or
code from that skin (GPL-2.0, based on GeometryCosmic) are part of CR8TXXX.

Mixxx is a trademark of the Mixxx project; CR8TXXX is not part of or endorsed by Mixxx. It
reads and writes the library database that Mixxx keeps.
