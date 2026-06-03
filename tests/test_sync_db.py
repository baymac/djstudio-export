"""Tests for sync/db.py — canonical track store + playlist membership. Temp DB per test."""
import sqlite3

import pytest

import sync.db as sdb


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "sync_test.db"
    monkeypatch.setattr(sdb, "DB_PATH", path)
    sdb.init_db(path)
    return path


def test_init_db_creates_tables(tmp_db):
    con = sqlite3.connect(tmp_db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"sync_tracks", "sync_playlist_tracks", "auth_cache", "cursors"} <= tables
    # The old dedup tables are gone — capture is faithful, dedup happens at enrich.
    assert "synced_tracks" not in tables
    assert "sync_runs" not in tables


def test_init_db_idempotent(tmp_db):
    sdb.init_db(tmp_db)
    sdb.init_db(tmp_db)


def test_insert_sync_track_dedups_canonical_keeps_membership(tmp_db):
    # Same native track captured twice in a playlist → ONE canonical track row,
    # but TWO membership links (duplicates within a playlist are preserved).
    sdb.insert_sync_track("apple_music", native_track_id="t1", artist="A", title="T",
                          playlist_name="P", native_playlist_id="pid1", position=0, db_path=tmp_db)
    sdb.insert_sync_track("apple_music", native_track_id="t1", artist="A", title="T",
                          playlist_name="P", native_playlist_id="pid1", position=5, db_path=tmp_db)
    rows = sdb.get_unenriched_sync_tracks(db_path=tmp_db)
    assert len(rows) == 1  # canonical dedup by (app, native id)
    con = sqlite3.connect(tmp_db)
    n_members = con.execute("SELECT COUNT(*) FROM sync_playlist_tracks").fetchone()[0]
    con.close()
    assert n_members == 2


def test_replace_playlist_resnapshots_membership_preserves_tracks(tmp_db):
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "t1", "artist": "A", "title": "T1", "playlist_name": "P", "position": 0},
        {"native_track_id": "t2", "artist": "B", "title": "T2", "playlist_name": "P", "position": 1},
    ], db_path=tmp_db)
    # Re-sync: T1 removed from the playlist, T2 moved, T3 added.
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "t2", "artist": "B", "title": "T2", "playlist_name": "P", "position": 0},
        {"native_track_id": "t3", "artist": "C", "title": "T3", "playlist_name": "P", "position": 1},
    ], db_path=tmp_db)
    con = sqlite3.connect(tmp_db)
    # Playlist membership mirrors the new snapshot…
    members = {r[0] for r in con.execute(
        """SELECT t.title FROM sync_playlist_tracks m JOIN sync_tracks t ON t.id = m.sync_track_id
           WHERE m.native_playlist_id = 'pid1'""")}
    # …but the canonical store still has T1 — a playlist removal never loses data.
    all_tracks = {r[0] for r in con.execute("SELECT title FROM sync_tracks")}
    con.close()
    assert members == {"T2", "T3"}
    assert all_tracks == {"T1", "T2", "T3"}


def test_replace_playlist_returns_diff_stats(tmp_db):
    # First snapshot: everything is new.
    s1 = sdb.replace_playlist("spotify", "pid1", [
        {"native_track_id": "t1", "artist": "A", "title": "T1", "playlist_name": "P", "position": 0},
        {"native_track_id": "t2", "artist": "B", "title": "T2", "playlist_name": "P", "position": 1},
    ], db_path=tmp_db)
    assert s1 == {"new": 2, "kept": 0, "removed": 0, "total": 2}

    # Re-snapshot: t1 removed, t2 kept, t3 new.
    s2 = sdb.replace_playlist("spotify", "pid1", [
        {"native_track_id": "t2", "artist": "B", "title": "T2", "playlist_name": "P", "position": 0},
        {"native_track_id": "t3", "artist": "C", "title": "T3", "playlist_name": "P", "position": 1},
    ], db_path=tmp_db)
    assert s2 == {"new": 1, "kept": 1, "removed": 1, "total": 2}


def test_replace_playlist_scoped_per_playlist(tmp_db):
    sdb.replace_playlist("apple_music", "pidA", [
        {"native_track_id": "a", "artist": "A", "title": "Ta", "playlist_name": "A", "position": 0}],
        db_path=tmp_db)
    sdb.replace_playlist("apple_music", "pidB", [
        {"native_track_id": "b", "artist": "B", "title": "Tb", "playlist_name": "B", "position": 0}],
        db_path=tmp_db)
    # Replacing pidA must not touch pidB.
    sdb.replace_playlist("apple_music", "pidA", [], db_path=tmp_db)
    pls = {r["native_playlist_id"]: r["track_count"] for r in sdb.list_playlists("apple_music", db_path=tmp_db)}
    assert pls.get("pidB") == 1
    assert "pidA" not in pls  # empty after replace-with-nothing


def test_list_playlists_groups(tmp_db):
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "a", "artist": "A", "title": "T1", "playlist_name": "Mix", "position": 0},
        {"native_track_id": "b", "artist": "B", "title": "T2", "playlist_name": "Mix", "position": 1},
    ], db_path=tmp_db)
    rows = sdb.list_playlists("apple_music", db_path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["playlist_name"] == "Mix"
    assert rows[0]["track_count"] == 2


def test_persistent_id_stored_and_coalesced(tmp_db):
    # Apple persistent id rides along on the playlist row…
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "t1", "artist": "A", "title": "T",
         "native_persistent_id": "ABC123", "playlist_name": "P", "position": 0}],
        db_path=tmp_db)
    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row
    got = con.execute("SELECT native_persistent_id FROM sync_tracks").fetchone()
    assert got["native_persistent_id"] == "ABC123"
    # …and a later capture WITHOUT it must not wipe the stored value (COALESCE).
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "t1", "artist": "A", "title": "T", "playlist_name": "P", "position": 0}],
        db_path=tmp_db)
    got2 = con.execute("SELECT native_persistent_id FROM sync_tracks").fetchone()
    con.close()
    assert got2["native_persistent_id"] == "ABC123"


def test_migrate_adds_persistent_id_column_to_old_split_db(tmp_path, monkeypatch):
    # A pre-existing split DB lacking the column gets it added (additive migration).
    path = tmp_path / "old_split.db"
    con = sqlite3.connect(path)
    # The pre-change split schema: everything except native_persistent_id.
    con.executescript(
        "CREATE TABLE sync_tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT NOT NULL, "
        "dedup_key TEXT NOT NULL, native_track_id TEXT, native_url TEXT, artist TEXT, title TEXT, "
        "album TEXT, captured_at TEXT NOT NULL, enrich_outcome TEXT, enriched_beatport_id INTEGER, "
        "UNIQUE(app, dedup_key));"
        "CREATE TABLE sync_playlist_tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT NOT NULL, "
        "native_playlist_id TEXT NOT NULL, playlist_name TEXT, sync_track_id INTEGER, position INTEGER);"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(sdb, "DB_PATH", path)
    sdb.init_db(path)
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sync_tracks)")}
    con.close()
    assert "native_persistent_id" in cols


def test_tracks_in_native_playlist_ordered_full_rows(tmp_db):
    sdb.replace_playlist("apple_music", "__library__", [
        {"native_track_id": "c1", "artist": "A", "title": "T1", "album": "Al1",
         "native_persistent_id": "P1", "playlist_name": "Library", "position": 1},
        {"native_track_id": "c2", "artist": "B", "title": "T2", "album": "Al2",
         "native_persistent_id": "P2", "playlist_name": "Library", "position": 0},
    ], db_path=tmp_db)
    rows = sdb.tracks_in_native_playlist("apple_music", "__library__", db_path=tmp_db)
    # ordered by position, and carries the columns restore needs
    assert [r["title"] for r in rows] == ["T2", "T1"]
    assert rows[0]["native_track_id"] == "c2"
    assert rows[0]["native_persistent_id"] == "P2"
    assert rows[1]["album"] == "Al1"


def test_no_db_side_delete_for_captured_playlists(tmp_db):
    # dj.db is the permanent backup: `playlist delete` removes from the source app,
    # never from our DB. The old local-clear helpers are intentionally gone.
    assert not hasattr(sdb, "clear_playlist")
    assert not hasattr(sdb, "clear_all")


def test_get_unenriched_excludes_marked(tmp_db):
    rid_found = sdb.insert_sync_track("apple_music", artist="A", title="T1", db_path=tmp_db)
    rid_miss = sdb.insert_sync_track("apple_music", artist="B", title="T2", db_path=tmp_db)
    sdb.mark_sync_enriched(rid_found, 111, db_path=tmp_db)
    sdb.mark_sync_miss(rid_miss, "not_found", db_path=tmp_db)
    sdb.insert_sync_track("apple_music", artist="C", title="T3", db_path=tmp_db)
    pending = sdb.get_unenriched_sync_tracks(db_path=tmp_db)
    assert {r["title"] for r in pending} == {"T3"}


def test_unenriched_aliases_app_as_source(tmp_db):
    sdb.insert_sync_track("spotify", artist="A", title="T", db_path=tmp_db)
    row = sdb.get_unenriched_sync_tracks(db_path=tmp_db)[0]
    assert row["source"] == "spotify"  # shared enrich engine reads row["source"]


def test_mark_sync_duplicate_links_beatport_id(tmp_db):
    rid = sdb.insert_sync_track("apple_music", artist="A", title="T", db_path=tmp_db)
    sdb.mark_sync_duplicate(rid, 222, db_path=tmp_db)
    row = sdb.get_sync_track(rid, db_path=tmp_db)
    assert row["enrich_outcome"] == "duplicate"
    assert row["enriched_beatport_id"] == 222


_OLD_FLAT_SCHEMA = """
CREATE TABLE sync_tracks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    app                  TEXT    NOT NULL,
    native_track_id      TEXT,
    native_url           TEXT,
    artist               TEXT,
    title                TEXT,
    album                TEXT,
    playlist_name        TEXT,
    native_playlist_id   TEXT,
    position             INTEGER,
    captured_at          TEXT    NOT NULL,
    enrich_outcome       TEXT,
    enriched_beatport_id INTEGER
);
"""


def test_migrates_flat_schema_to_split(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(sdb, "DB_PATH", path)

    # Hand-build the pre-split flat table with: a track in two playlists, a dup
    # entry within one playlist, and one already-enriched row.
    con = sqlite3.connect(path)
    con.executescript(_OLD_FLAT_SCHEMA)
    con.executemany(
        """INSERT INTO sync_tracks
           (app, native_track_id, artist, title, playlist_name, native_playlist_id,
            position, captured_at, enrich_outcome, enriched_beatport_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [
            ("spotify", "x1", "A", "T1", "P1", "pid1", 0, "2025-01-01T00:00:00", "found", 555),
            ("spotify", "x1", "A", "T1", "P2", "pid2", 3, "2025-01-02T00:00:00", None, None),
            ("spotify", "x2", "B", "T2", "P1", "pid1", 1, "2025-01-01T00:00:00", None, None),
            ("spotify", "x2", "B", "T2", "P1", "pid1", 7, "2025-01-01T00:00:00", None, None),
        ],
    )
    con.commit()
    con.close()

    sdb.init_db(path)  # triggers migration

    con = sqlite3.connect(path)
    # Two canonical tracks (x1, x2), deduped across playlists/entries.
    canon = con.execute(
        "SELECT native_track_id, enrich_outcome, enriched_beatport_id FROM sync_tracks ORDER BY native_track_id"
    ).fetchall()
    # x1 carries the enriched state merged from its first playlist entry.
    assert canon == [("x1", "found", 555), ("x2", None, None)]
    # Membership preserved: pid1 has 3 entries (T1 + the dup T2 x2), pid2 has 1.
    counts = {r[0]: r[1] for r in con.execute(
        "SELECT native_playlist_id, COUNT(*) FROM sync_playlist_tracks GROUP BY native_playlist_id")}
    con.close()
    assert counts == {"pid1": 3, "pid2": 1}
    # Old flat table is gone.
    assert sdb.list_playlists("spotify", db_path=path)  # works against split schema


def test_cursor_get_set_overwrite(tmp_db):
    assert sdb.get_cursor("apple_music_library", db_path=tmp_db) is None
    sdb.set_cursor("apple_music_library", "2024-01-01T00:00:00", db_path=tmp_db)
    assert sdb.get_cursor("apple_music_library", db_path=tmp_db) == "2024-01-01T00:00:00"
    sdb.set_cursor("apple_music_library", "2025-06-01T00:00:00", db_path=tmp_db)
    assert sdb.get_cursor("apple_music_library", db_path=tmp_db) == "2025-06-01T00:00:00"
