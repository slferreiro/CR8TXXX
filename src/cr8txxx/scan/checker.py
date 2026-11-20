# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""Which music files are damaged. Taken from FMM's music file checker
(FMM 0.91.0, src/fmm/services/audio_check.py: the checking functions only; FMM's database,
job and progress code is left out), by the same author: MIT-licensed in FMM, part of
CR8TXXX here under the GPL-3.0-or-later.

The damage FMM found (2026-11-04): a 128 KB block of an MP3 overwritten with the block
before it. The song keeps its length, but a few seconds play twice, and the real audio of
those seconds is gone from the file. So an MP3 is read frame by frame (no decoding): a run
of frames identical to an earlier run is a repeat; bytes that aren't frames, in mid-file,
are a break. Silence is never a repeat: its frames are all alike. Other formats are decoded
by ffmpeg, counting its errors.

Statuses: ok, damaged (repeats, or decoding errors), suspect (breaks in an MP3: it may click
or skip), unreadable, unchecked (not an MP3 and no ffmpeg to decode it).
"""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cr8txxx.scan import ffmpeg

VERSION = 2  # FMM's: each file's format, bitrate and sample rate too
MIN_REPEAT = 50  # frames (1.3 s): a run identical to an earlier one is a repeat
MIN_DISTINCT = 40  # distinct frames in it: silence (all alike) never counts
MIN_BREAK = 32  # bytes between frames, in mid-file, that make a break
SAMPLES = {1: 1152, 2: 576}  # per Layer III frame, MPEG-1 and MPEG-2/2.5

_BITRATES = {
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_RATES = {1: [44100, 48000, 32000, 0], 2: [22050, 24000, 16000, 0], 25: [11025, 12000, 8000, 0]}


def _frame(data: bytes, i: int) -> tuple[int, int, int] | None:
    """An MPEG Layer III frame header at ``i``: (its size in bytes, samples, sample rate)."""
    if i + 4 > len(data) or data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
        return None
    version_bits, layer = (data[i + 1] >> 3) & 3, (data[i + 1] >> 1) & 3
    if layer != 1 or version_bits == 1:  # Layer III only; 01 is reserved
        return None
    version = {3: 1, 2: 2, 0: 25}[version_bits]
    table = 1 if version == 1 else 2
    bitrate = _BITRATES[table][data[i + 2] >> 4]
    rate = _RATES[version][(data[i + 2] >> 2) & 3]
    if not bitrate or not rate:
        return None
    padding = (data[i + 2] >> 1) & 1
    samples = SAMPLES[table]
    size = (samples // 8) * bitrate * 1000 // rate + padding
    return size, samples, rate


def _start(data: bytes) -> int:
    """Where the audio starts: after an ID3v2 tag."""
    if data[:3] == b"ID3" and len(data) >= 10:
        return 10 + (
            (data[6] & 0x7F) << 21
            | (data[7] & 0x7F) << 14
            | (data[8] & 0x7F) << 7
            | (data[9] & 0x7F)
        )
    return 0


def _tail(data: bytes, i: int) -> bool:
    """Whether what's left from ``i`` is only tags (ID3v1, APE, Lyrics3) or padding."""
    rest = data[i:]
    tags = b"TAG" in rest[-128:] or b"APETAGEX" in rest or not rest.strip(b"\0")
    return len(rest) <= 2048 and tags


def check_mp3(data: bytes) -> dict[str, Any]:
    """Repeats and breaks in an MP3's frames."""
    i = _start(data)
    hashes: list[bytes] = []
    seconds: list[float] = []  # each frame's start
    clock = 0.0
    breaks = 0
    bytes_in_frames = 0
    first: tuple[int, int] | None = None  # (sample rate, channels) of the first frame
    while i + 4 <= len(data):
        found = _frame(data, i)
        if found is not None and found[0] > 4:
            size, samples, rate = found
            if first is None:
                first = (rate, 1 if data[i + 3] >> 6 == 3 else 2)  # channel mode 3: mono
            bytes_in_frames += size
            hashes.append(hashlib.md5(data[i : i + size]).digest())
            seconds.append(clock)
            clock += samples / rate
            i += size
            continue
        start = i
        while i + 4 <= len(data) and _frame(data, i) is None:
            i += 1
        if i + 4 > len(data) or _tail(data, start):
            break  # the end: tags or padding
        if i - start > MIN_BREAK:
            breaks += 1
    repeats = _repeats(hashes, seconds)
    facts: dict[str, Any] = {"format": "mp3", "lossless": False}
    if clock and first:  # the true average: right for variable bitrate too
        facts.update(bitrate=round(bytes_in_frames * 8 / clock / 1000), rate=first[0],
                     channels=first[1])  # fmt: skip
    return {"frames": len(hashes), "seconds": round(clock, 2), "repeats": repeats,
            "breaks": breaks, **facts}  # fmt: skip


def _repeats(hashes: list[bytes], seconds: list[float]) -> list[dict[str, float]]:
    first: dict[bytes, int] = {}
    for n, h in enumerate(hashes):
        first.setdefault(h, n)
    found = []
    n = 0
    while n < len(hashes):
        earlier = first[hashes[n]]
        if earlier < n and (n == 0 or hashes[n] != hashes[n - 1]):
            k = 0
            while n + k < len(hashes) and earlier + k < n and hashes[earlier + k] == hashes[n + k]:
                k += 1
            if k >= MIN_REPEAT and len(set(hashes[n : n + k])) >= MIN_DISTINCT:
                end = seconds[n + k] if n + k < len(seconds) else seconds[-1]
                found.append(
                    {
                        "at": round(seconds[n], 2),
                        "copy_of": round(seconds[earlier], 2),
                        "seconds": round(end - seconds[n], 2),
                    }
                )
                n += k
                continue
        n += 1
    return found


LOSSLESS = {"alac", "flac", "pcm", "wavpack", "ape", "tta", "mlp", "truehd"}


def probe_facts(tool: ffmpeg.Tool, path: str) -> dict[str, Any]:
    """Other formats' facts, from ffprobe: the codec (Apple Lossless or AAC in an .m4a),
    bitrate, sample rate, bit depth and channels."""
    try:
        done = subprocess.run(
            [tool.ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels,bits_per_raw_sample,bits_per_sample,bit_rate"
             ":format=bit_rate", "-of", "json", path],
            capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip
        data = json.loads(done.stdout or "{}")
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return {}
    streams = data.get("streams") or []
    if not streams:
        return {}
    stream = streams[0]
    codec = str(stream.get("codec_name") or "")
    codec = "pcm" if codec.startswith("pcm_") else codec
    bitrate = int(stream.get("bit_rate") or (data.get("format") or {}).get("bit_rate") or 0)
    bits = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0)
    facts: dict[str, Any] = {"format": codec, "lossless": codec in LOSSLESS}
    if bitrate:
        facts["bitrate"] = round(bitrate / 1000)
    if stream.get("sample_rate"):
        facts["rate"] = int(stream["sample_rate"])
    if stream.get("channels"):
        facts["channels"] = int(stream["channels"])
    if bits and facts["lossless"]:
        facts["bits"] = bits
    return facts


def check_decoded(tool: ffmpeg.Tool, path: str) -> dict[str, Any]:
    """Other formats: ffmpeg decodes the file; its errors are damage."""
    try:
        done = subprocess.run(
            [tool.ffmpeg, "-v", "error", "-nostdin", "-i", path, "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"errors": 1, "unreadable": True}
    errors = [line for line in done.stderr.splitlines() if line.strip()]
    # "[aac @ 0x7a88…] Input buffer exhausted…": ffmpeg's own prefixes say nothing to a person
    words = re.sub(r"^(\[[^\]]*\]\s*)+", "", errors[0]) if errors else ""
    return {
        "errors": len(errors),
        "first_error": words[:200],
        "unreadable": done.returncode != 0 and not errors,
    }


def check_file(path: str, tool: ffmpeg.Tool | None) -> dict[str, Any]:
    """The check's result for one file (it isn't changed)."""
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return {"v": VERSION, "status": "unreadable", "why": "the file can't be read"}
    result: dict[str, Any] = {
        "v": VERSION,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "checked": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    kind = p.suffix.lower().lstrip(".")
    try:
        if kind in ("mp3", "mp2"):
            found = check_mp3(p.read_bytes())
            result.update(found)
            status = "damaged" if found["repeats"] else "suspect" if found["breaks"] else "ok"
            result["status"] = status
        elif tool is not None:
            found = check_decoded(tool, path)
            result.update(probe_facts(tool, path))
            result.update(found)
            result["status"] = (
                "unreadable" if found.get("unreadable") else "damaged" if found["errors"] else "ok"
            )
        else:
            result["status"] = "unchecked"  # no ffmpeg: only MP3s can be checked
    except OSError as exc:
        return {"v": VERSION, "status": "unreadable", "why": str(exc)[:200]}
    return result


NAMES = {"mp3": "MP3", "aac": "AAC", "alac": "Apple Lossless", "flac": "FLAC", "pcm": "PCM",
         "mp2": "MP2", "vorbis": "Ogg Vorbis", "opus": "Opus", "wavpack": "WavPack"}  # fmt: skip


def facts_line(check: dict[str, Any] | None) -> str:
    """A file's facts in a few words: "MP3 · 160 kbps", "Apple Lossless · 24-bit/96 kHz"."""
    check = check or {}
    if not check.get("format"):
        return ""
    name = NAMES.get(check["format"], str(check["format"]).upper())
    rate = check.get("rate")
    if check.get("lossless"):
        depth = f"{check['bits']}-bit/" if check.get("bits") else ""
        return f"{name} · {depth}{rate / 1000:g} kHz" if rate else name
    return f"{name} · {check['bitrate']} kbps" if check.get("bitrate") else name


def describe(check: dict[str, Any]) -> str:
    """What's wrong, in a line."""

    def clock(s: float) -> str:
        return f"{int(s) // 60}:{int(s) % 60:02d}"

    if check.get("repeats"):
        return "; ".join(
            f"{r['seconds']:.1f} s repeated at {clock(r['at'])} (a copy of {clock(r['copy_of'])})"
            for r in check["repeats"]
        )
    if check.get("status") == "suspect":
        n = check.get("breaks", 0)
        return f"{n} break{'s' if n != 1 else ''} in the audio (it may click or skip)"
    if check.get("errors"):
        first = f": {check['first_error']}" if check.get("first_error") else ""
        return f"{check['errors']} decoding errors{first}"
    if check.get("status") == "unchecked":
        return "not checked: needs ffmpeg (brew install ffmpeg)"
    return str(check.get("why") or "can't be read")
