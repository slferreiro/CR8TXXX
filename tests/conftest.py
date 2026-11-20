# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Sean Ferreiro
"""A small Mixxx library to test on: Mixxx 2.5's tables (the columns CR8TXXX uses and the
constraints that matter), three tracks with real files, and one crate."""

import sqlite3
from pathlib import Path

import pytest

from cr8txxx import paths
from cr8txxx.db.mixxx import Library

SCHEMA = """
CREATE TABLE settings (name TEXT UNIQUE NOT NULL, value TEXT, locked INTEGER DEFAULT 0,
  hidden INTEGER DEFAULT 0);
CREATE TABLE track_locations (id INTEGER PRIMARY KEY AUTOINCREMENT,
  location varchar(512) UNIQUE, filename varchar(512), directory varchar(512),
  filesize INTEGER, fs_deleted INTEGER, needs_verification INTEGER);
CREATE TABLE library (id INTEGER PRIMARY KEY AUTOINCREMENT, artist varchar(64),
  title varchar(64), album varchar(64), year varchar(16), genre varchar(64),
  tracknumber varchar(3), location integer REFERENCES track_locations(location),
  comment varchar(256), url varchar(256), duration float, bitrate integer,
  samplerate integer, cuepoint integer, bpm float, wavesummaryhex blob, channels integer,
  datetime_added DEFAULT CURRENT_TIMESTAMP, mixxx_deleted integer, played integer,
  header_parsed integer DEFAULT 0, filetype varchar(8) DEFAULT "?",
  replaygain float DEFAULT 0, timesplayed integer DEFAULT 0, rating integer DEFAULT 0,
  key varchar(8) DEFAULT "", composer varchar(64) DEFAULT "", bpm_lock INTEGER DEFAULT 0,
  key_id INTEGER DEFAULT 0, grouping TEXT DEFAULT "", album_artist TEXT DEFAULT "",
  tracktotal TEXT DEFAULT '//', color INTEGER, last_played_at DATETIME DEFAULT NULL,
  source_synchronized_ms INTEGER DEFAULT NULL);
CREATE TABLE crates (id INTEGER PRIMARY KEY AUTOINCREMENT, name varchar(48) UNIQUE NOT NULL,
  count INTEGER DEFAULT 0, show INTEGER DEFAULT 1, locked INTEGER DEFAULT 0,
  autodj_source INTEGER DEFAULT 0);
CREATE TABLE crate_tracks (crate_id INTEGER NOT NULL REFERENCES crates(id),
  track_id INTEGER NOT NULL REFERENCES library(id), UNIQUE (crate_id, track_id));
CREATE TABLE Playlists (id INTEGER PRIMARY KEY, name varchar(48), position INTEGER,
  hidden INTEGER DEFAULT 0 NOT NULL, date_created datetime, date_modified datetime,
  locked INTEGER DEFAULT 0);
CREATE TABLE PlaylistTracks (id INTEGER PRIMARY KEY, playlist_id INTEGER REFERENCES
  Playlists(id), track_id INTEGER REFERENCES library(id), position INTEGER,
  pl_datetime_added TEXT);
CREATE TABLE cues (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER NOT NULL
  REFERENCES library(id), type INTEGER DEFAULT 0 NOT NULL, position INTEGER DEFAULT -1);
CREATE TABLE track_analysis (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER NOT NULL
  REFERENCES library(id), type varchar(512), description varchar(1024));
CREATE TABLE directories (directory TEXT UNIQUE);
INSERT INTO settings (name, value) VALUES ('mixxx.schema.version', '39');
"""


def make_db(folder: Path) -> Path:
    music = folder / "Music"
    music.mkdir()
    db = folder / "mixxxdb.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO directories VALUES (?)", (str(music),))
    for n, (artist, title) in enumerate(
        [("Daft Punk", "One More Time"), ("Moby", "Porcelain"), ("Air", "La Femme d'Argent")],
        start=1,
    ):
        f = music / f"{n:02d} {title}.mp3"
        f.write_bytes(b"\0" * (1000 * n))
        conn.execute(
            "INSERT INTO track_locations (id, location, filename, directory, filesize,"
            " fs_deleted, needs_verification) VALUES (?, ?, ?, ?, ?, 0, 0)",
            (n, str(f), f.name, str(music), 1000 * n),
        )
        conn.execute(
            "INSERT INTO library (id, artist, title, location, mixxx_deleted, bpm, filetype)"
            " VALUES (?, ?, ?, ?, 0, ?, 'mp3')",
            (n, artist, title, n, 120 + n),
        )
    conn.execute("INSERT INTO crates (id, name) VALUES (1, 'Warmup')")
    conn.execute("INSERT INTO crate_tracks VALUES (1, 1), (1, 2)")
    conn.execute("INSERT INTO cues (track_id) VALUES (1)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Backups go into the test's folder, never the real Application Support."""
    monkeypatch.setattr(paths, "HOME", tmp_path / "home")


@pytest.fixture
def running() -> dict[str, bool]:
    return {"mixxx": False}


@pytest.fixture
def lib(tmp_path: Path, running: dict[str, bool]) -> Library:
    library = Library(make_db(tmp_path), running=lambda: running["mixxx"])
    yield library
    library.close()
