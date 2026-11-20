#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
# The installer: a DMG holding CR8TXXX.app, a link to Applications and "Read Me First".
#   make_dmg.sh <CR8TXXX.app> <out.dmg> [signing identity]
set -eu
app="$1"
dmg="$2"
identity="${3:-}"
here="$(cd "$(dirname "$0")" && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
cp "$here/Read Me First.txt" "$stage/"
cp "$here/../LICENSE" "$stage/License (GPL-3.0).txt"
cp "$here/../THIRD_PARTY_NOTICES.md" "$stage/Third-Party Notices.md"
rm -f "$dmg"
hdiutil create -volname "CR8TXXX" -srcfolder "$stage" -fs HFS+ -format UDZO -ov "$dmg" >/dev/null
if [ -n "$identity" ]; then
	codesign --force --timestamp --sign "$identity" "$dmg"
fi
echo "Built $dmg"
