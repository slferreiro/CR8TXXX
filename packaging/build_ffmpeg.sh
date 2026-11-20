#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
# Builds the ffmpeg and ffprobe that CR8TXXX.app carries for its damaged-file scan:
# audio only (decoders, demuxers and parsers for the formats Mixxx plays), no network,
# no video, no external libraries, LGPL (no --enable-gpl), statically linked: two files
# that only need macOS itself. Apple silicon (arm64), macOS 13 or later.
#
#   packaging/build_ffmpeg.sh <build folder>     → <build folder>/ffmpeg-bin/{ffmpeg,ffprobe}
set -eu
VERSION=7.1.1
BUILD="${1:?usage: build_ffmpeg.sh <build folder>}"
SRC="$BUILD/ffmpeg-src"
OUT="$BUILD/ffmpeg-bin"
mkdir -p "$SRC" "$OUT"

if [ -x "$OUT/ffmpeg" ] && [ -x "$OUT/ffprobe" ] && "$OUT/ffmpeg" -version | grep -q "version $VERSION"; then
	echo "ffmpeg $VERSION already built in $OUT"
	exit 0
fi

tarball="$SRC/ffmpeg-$VERSION.tar.xz"
[ -f "$tarball" ] || curl -fL --retry 3 -o "$tarball" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
rm -rf "$SRC/ffmpeg-$VERSION"
tar -xJf "$tarball" -C "$SRC"
cd "$SRC/ffmpeg-$VERSION"

DECODERS="mp3,mp3float,mp2,mp2float,mp1,mp1float,aac,aac_fixed,aac_latm,alac,flac,vorbis,opus,\
wavpack,ape,tta,wmav1,wmav2,wmapro,wmalossless,ac3,eac3,pcm_s8,pcm_u8,pcm_s16le,pcm_s16be,\
pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_alaw,\
pcm_mulaw,adpcm_ima_qt,adpcm_ms"
DEMUXERS="mp3,aac,mov,flac,wav,w64,aiff,ogg,matroska,wv,ape,tta,caf,asf,ac3,eac3"
PARSERS="mpegaudio,aac,aac_latm,flac,vorbis,opus,ac3"

./configure \
	--prefix="$SRC/install" \
	--arch=arm64 --target-os=darwin --cc=clang \
	--extra-cflags="-mmacosx-version-min=13.0" --extra-ldflags="-mmacosx-version-min=13.0" \
	--enable-static --disable-shared \
	--disable-everything --disable-autodetect --disable-network --disable-doc \
	--disable-debug --disable-ffplay --disable-avdevice --disable-swscale \
	--enable-ffmpeg --enable-ffprobe --enable-swresample \
	--enable-protocol=file,pipe \
	--enable-decoder="$DECODERS" --enable-demuxer="$DEMUXERS" --enable-parser="$PARSERS" \
	--enable-muxer=null --enable-encoder=pcm_s16le \
	--enable-filter=aresample,aformat,anull,atrim,null,format

make -j"$(sysctl -n hw.ncpu)"
cp ffmpeg ffprobe "$OUT/"
strip -x "$OUT/ffmpeg" "$OUT/ffprobe" 2>/dev/null || true
echo "Built ffmpeg $VERSION (audio only, LGPL) in $OUT"
"$OUT/ffmpeg" -hide_banner -version | head -3
otool -L "$OUT/ffmpeg"
