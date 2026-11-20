#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
# Signs CR8TXXX.app (from FMM's packaging/sign.sh).
#   sign.sh CR8TXXX.app ""            ad-hoc (no Apple Developer account)
#   sign.sh CR8TXXX.app "<identity>"  Developer ID ("Developer ID Application: Name (TEAM)"):
#                                     every library and the bundled ffmpeg, then the app,
#                                     with the hardened runtime and a secure timestamp
set -eu
app="$1"
identity="${2:-}"
here="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$identity" ]; then
	codesign --force --deep --sign - "$app"
	codesign --force --sign - -r='designated => identifier "com.cr8txxx.app"' "$app"
else
	# Inside out: libraries and the ffmpeg tools, then the frameworks that hold them, then the app.
	find "$app/Contents" -type f \( -name '*.so' -o -name '*.dylib' -o -path '*/ffmpeg-bin/ff*' \) -print0 |
		xargs -0 -n 50 codesign --force --timestamp --options runtime --sign "$identity"
	find "$app/Contents/Frameworks" -type d -name '*.framework' -prune -print |
		while IFS= read -r framework; do
			codesign --force --timestamp --options runtime --sign "$identity" "$framework"
		done
	codesign --force --timestamp --options runtime \
		--entitlements "$here/entitlements.plist" --sign "$identity" "$app"
fi
codesign --verify --deep --strict "$app"
