"""SQLite persistence for `dj sync` capture (unified dj.db).

The capture store is split into two tables, mirroring the Beatport side
(`enriched_tracks` + `beatport_playlist_tracks`):

* `sync_tracks` — the CANONICAL, per-(app, track) store. Append-only / upsert,
  keyed by `(app, dedup_key)` (the app's native track id when present, else a
  normalised artist+title). A track row is NEVER deleted by a re-sync, so a
  delete on the source app's side cannot destroy captured data. Enrich state
  (`enrich_outcome`, `enriched_beatport_id`) lives here, once per unique track.
* `sync_playlist_tracks` — playlist MEMBERSHIP links (playlist → track + position).
  Re-syncing a playlist re-snapshots only its membership rows, so removed tracks
  drop out of the playlist while their canonical `sync_tracks` row survives.

`cursors` powers incremental `--library` capture (skip already-seen additions).
`auth_cache` stores per-service refresh tokens (e.g. Spotify).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from paths import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_tracks (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app                   TEXT    NOT NULL,
    dedup_key             TEXT    NOT NULL,
    native_track_id       TEXT,
    native_url            TEXT,
    native_persistent_id  TEXT,
    artist                TEXT,
    title                 TEXT,
    album                 TEXT,
    captured_at           TEXT    NOT NULL,
    enrich_outcome        TEXT,
    enriched_beatport_id  INTEGER,
    UNIQUE(app, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_sync_tracks_enrich ON sync_tracks(app, enrich_outcome);

CREATE TABLE IF NOT EXISTS sync_playlist_tracks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    app                TEXT    NOT NULL,
    native_playlist_id TEXT    NOT NULL,
    playlist_name      TEXT,
    sync_track_id      INTEGER NOT NULL REFERENCES sync_tracks(id) ON DELETE CASCADE,
    position           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_spt_playlist ON sync_playlist_tracks(app, native_playlist_id);
CREATE INDEX IF NOT EXISTS idx_spt_track    ON sync_playlist_tracks(sync_track_id);

CREATE TABLE IF NOT EXISTS auth_cache (
    service      TEXT NOT NULL PRIMARY KEY,
    token        TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    expires_at   TEXT
);

CREATE TABLE IF NOT EXISTS cursors (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Outcomes that mean "don't reprocess on a normal enrich run".
_TERMINAL_OUTCOMES = ("found", "duplicate", "secret")
_RETRY_OUTCOMES = ("not_found", "fuzzy_miss")

# Enrich-outcome precedence when merging duplicate rows during migration.
_OUTCOME_RANK = {"found": 5, "duplicate": 4, "secret": 3, "not_found": 2, "fuzzy_miss": 1}


@contextmanager
def _conn(db_path: Path | None = None):
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedup_key(native_track_id: Optional[str], artist: Optional[str], title: Optional[str]) -> str:
    """Stable per-track identity: native id when present, else normalised artist+title."""
    nid = (native_track_id or "").strip()
    if nid:
        return nid
    a = (artist or "").strip().lower()
    t = (title or "").strip().lower()
    return f"\x00{a}\x01{t}"


def _columns(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def init_db(db_path: Path | None = None) -> None:
    with _conn(db_path) as con:
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Migrate a pre-split flat sync_tracks (had native_playlist_id/position columns)
        # into the canonical-tracks + membership split before creating the new schema.
        if "sync_tracks" in existing and "native_playlist_id" in _columns(con, "sync_tracks"):
            _migrate_flat_to_split(con)
        con.executescript(_SCHEMA)
        # Additive: persistent-ID column for Apple Music exact-restore (older DBs).
        if "sync_tracks" in existing and "native_persistent_id" not in _columns(con, "sync_tracks"):
            con.execute("ALTER TABLE sync_tracks ADD COLUMN native_persistent_id TEXT")


def _migrate_flat_to_split(con) -> None:
    """One-time: fold the old flat sync_tracks into sync_tracks + sync_playlist_tracks.

    Old rows were one-per-playlist-entry (duplicates across playlists). We collapse
    them to one canonical track per (app, dedup_key), carry the best enrich state,
    and rebuild playlist membership from each old row's native_playlist_id/position.
    """
    old_rows = con.execute("SELECT * FROM sync_tracks").fetchall()
    con.execute("ALTER TABLE sync_tracks RENAME TO _sync_tracks_flat_old")
    con.executescript(_SCHEMA)

    # Collapse to canonical tracks.
    canon: dict[tuple, dict] = {}
    for r in old_rows:
        key = _dedup_key(r["native_track_id"], r["artist"], r["title"])
        ck = (r["app"], key)
        c = canon.get(ck)
        if c is None:
            c = {
                "native_track_id": r["native_track_id"],
                "native_url": r["native_url"],
                "artist": r["artist"],
                "title": r["title"],
                "album": r["album"],
                "captured_at": r["captured_at"] or _now(),
                "outcome": r["enrich_outcome"],
                "beatport_id": r["enriched_beatport_id"],
            }
            canon[ck] = c
        else:
            # Keep first non-null field values; carry the highest-ranked enrich outcome.
            for f in ("native_track_id", "native_url", "artist", "title", "album"):
                if not c[f] and r[f]:
                    c[f] = r[f]
            if r["captured_at"] and r["captured_at"] < c["captured_at"]:
                c["captured_at"] = r["captured_at"]
            if c["beatport_id"] is None and r["enriched_beatport_id"] is not None:
                c["beatport_id"] = r["enriched_beatport_id"]
            if _OUTCOME_RANK.get(r["enrich_outcome"] or "", 0) > _OUTCOME_RANK.get(c["outcome"] or "", 0):
                c["outcome"] = r["enrich_outcome"]

    track_id: dict[tuple, int] = {}
    for (app, key), c in canon.items():
        cur = con.execute(
            """INSERT INTO sync_tracks
               (app, dedup_key, native_track_id, native_url, artist, title, album,
                captured_at, enrich_outcome, enriched_beatport_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (app, key, c["native_track_id"], c["native_url"], c["artist"], c["title"],
             c["album"], c["captured_at"], c["outcome"], c["beatport_id"]),
        )
        track_id[(app, key)] = cur.lastrowid

    # Rebuild membership from old rows that belonged to a playlist.
    for r in old_rows:
        npid = r["native_playlist_id"]
        if not npid:
            continue
        key = _dedup_key(r["native_track_id"], r["artist"], r["title"])
        con.execute(
            """INSERT INTO sync_playlist_tracks
               (app, native_playlist_id, playlist_name, sync_track_id, position)
               VALUES (?, ?, ?, ?, ?)""",
            (r["app"], npid, r["playlist_name"], track_id[(r["app"], key)], r["position"]),
        )

    con.execute("DROP TABLE _sync_tracks_flat_old")


# ── Capture ────────────────────────────────────────────────────────────────────


def _upsert_track(
    con,
    app: str,
    native_track_id: Optional[str],
    native_url: Optional[str],
    artist: Optional[str],
    title: Optional[str],
    album: Optional[str],
    native_persistent_id: Optional[str] = None,
) -> tuple[int, str, bool]:
    """Insert-or-update one canonical track. Returns (track_id, dedup_key, is_new).

    Never overwrites a stored field with NULL (COALESCE keeps existing values).
    `native_persistent_id` is the Apple Music library track's stable persistent ID,
    used for exact restore (`playlist push`); NULL for other sources.
    """
    key = _dedup_key(native_track_id, artist, title)
    before = con.execute(
        "SELECT id FROM sync_tracks WHERE app = ? AND dedup_key = ?", (app, key)
    ).fetchone()
    con.execute(
        """INSERT INTO sync_tracks
             (app, dedup_key, native_track_id, native_url, native_persistent_id,
              artist, title, album, captured_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(app, dedup_key) DO UPDATE SET
             native_track_id      = COALESCE(excluded.native_track_id, native_track_id),
             native_url           = COALESCE(excluded.native_url, native_url),
             native_persistent_id = COALESCE(excluded.native_persistent_id, native_persistent_id),
             artist               = COALESCE(excluded.artist, artist),
             title                = COALESCE(excluded.title, title),
             album                = COALESCE(excluded.album, album)""",
        (app, key, native_track_id, native_url, native_persistent_id,
         artist, title, album, _now()),
    )
    if before:
        return before["id"], key, False
    row = con.execute(
        "SELECT id FROM sync_tracks WHERE app = ? AND dedup_key = ?", (app, key)
    ).fetchone()
    return row["id"], key, True


def insert_sync_track(
    app: str,
    *,
    native_track_id: Optional[str] = None,
    native_url: Optional[str] = None,
    native_persistent_id: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    album: Optional[str] = None,
    playlist_name: Optional[str] = None,
    native_playlist_id: Optional[str] = None,
    position: Optional[int] = None,
    db_path: Path | None = None,
) -> int:
    """Upsert one canonical track; optionally link it to a playlist. Returns track id.

    The canonical track is deduped by (app, native id | artist+title), so capturing
    the same track again updates in place rather than creating a duplicate row.
    """
    with _conn(db_path) as con:
        track_id, _, _ = _upsert_track(con, app, native_track_id, native_url, artist, title,
                                       album, native_persistent_id)
        if native_playlist_id:
            con.execute(
                """INSERT INTO sync_playlist_tracks
                   (app, native_playlist_id, playlist_name, sync_track_id, position)
                   VALUES (?, ?, ?, ?, ?)""",
                (app, native_playlist_id, playlist_name, track_id, position),
            )
        return track_id


def replace_playlist(
    app: str,
    native_playlist_id: str,
    rows: list[dict],
    db_path: Path | None = None,
) -> dict:
    """Re-snapshot one playlist's MEMBERSHIP; never deletes canonical tracks.

    Each track in `rows` is upserted into `sync_tracks` (preserved across re-syncs),
    then the playlist's membership links are deleted and re-inserted in order, so the
    playlist faithfully mirrors its current upstream contents (positions rewritten,
    duplicates preserved) while removed tracks merely lose their link.

    Each row dict may carry: native_track_id, native_url, artist, title, album,
    playlist_name, position.

    Returns a stats dict diffing the previous membership against the new one (by
    distinct track identity): ``{"new", "kept", "removed", "total"}``. "removed"
    tracks are unlinked from THIS playlist but their canonical row survives.
    """
    with _conn(db_path) as con:
        old_keys = {
            r[0] for r in con.execute(
                """SELECT DISTINCT t.dedup_key
                   FROM sync_playlist_tracks m
                   JOIN sync_tracks t ON t.id = m.sync_track_id
                   WHERE m.app = ? AND m.native_playlist_id = ?""",
                (app, native_playlist_id),
            )
        }

        members: list[tuple] = []
        new_keys: set[str] = set()
        for r in rows:
            track_id, key, _ = _upsert_track(
                con, app, r.get("native_track_id"), r.get("native_url"),
                r.get("artist"), r.get("title"), r.get("album"),
                r.get("native_persistent_id"),
            )
            new_keys.add(key)
            members.append((app, native_playlist_id, r.get("playlist_name"), track_id, r.get("position")))

        con.execute(
            "DELETE FROM sync_playlist_tracks WHERE app = ? AND native_playlist_id = ?",
            (app, native_playlist_id),
        )
        con.executemany(
            """INSERT INTO sync_playlist_tracks
               (app, native_playlist_id, playlist_name, sync_track_id, position)
               VALUES (?, ?, ?, ?, ?)""",
            members,
        )
        return {
            "new": len(new_keys - old_keys),
            "kept": len(new_keys & old_keys),
            "removed": len(old_keys - new_keys),
            "total": len(rows),
        }


def list_playlists(app: str, db_path: Path | None = None) -> list[sqlite3.Row]:
    """Captured playlists for an app: (native_playlist_id, playlist_name, track_count)."""
    with _conn(db_path) as con:
        return con.execute(
            """SELECT native_playlist_id, playlist_name, COUNT(*) AS track_count
               FROM sync_playlist_tracks
               WHERE app = ?
               GROUP BY native_playlist_id, playlist_name
               ORDER BY playlist_name""",
            (app,),
        ).fetchall()


def tracks_in_native_playlist(app: str, native_playlist_id: str,
                              db_path: Path | None = None) -> list[sqlite3.Row]:
    """Full sync_tracks rows for one captured playlist (or `__library__`/`__favorites__`), in order.

    Used by bulk restore (`playlist push --all/--playlists/--library/--favorite-only`).
    Returns whole rows (artist/title/album/native_track_id/native_persistent_id) so
    the restore can match by persistent id and re-add by catalog id.
    """
    with _conn(db_path) as con:
        return con.execute(
            """SELECT t.* FROM sync_tracks t
               JOIN sync_playlist_tracks m ON m.sync_track_id = t.id
               WHERE m.app = ? AND m.native_playlist_id = ?
               ORDER BY m.position""",
            (app, native_playlist_id),
        ).fetchall()


# `dj.db` is the permanent backup — there is intentionally no DB-side delete for
# captured playlists/tracks. `dj sync <app> playlist delete` removes a playlist
# from the SOURCE APP only (see sync/cli.py); the captured rows here are kept.


# ── Enrich support (shared engine adapter) ──────────────────────────────────────


def get_unenriched_sync_tracks(db_path: Path | None = None) -> list[sqlite3.Row]:
    """Candidate canonical tracks for enrich: not yet enriched, with artist+title.

    `app` is aliased to `source` so the shared enrich engine (which reads
    `track["source"]`) works unchanged.
    """
    with _conn(db_path) as con:
        return con.execute(
            """SELECT id, artist, title, app AS source
               FROM sync_tracks
               WHERE enrich_outcome IS NULL
                 AND artist IS NOT NULL AND title IS NOT NULL
               ORDER BY id""",
        ).fetchall()


def get_retry_sync_tracks(db_path: Path | None = None) -> list[sqlite3.Row]:
    with _conn(db_path) as con:
        return con.execute(
            """SELECT id, artist, title, app AS source
               FROM sync_tracks
               WHERE enrich_outcome IN ('not_found', 'fuzzy_miss')
                 AND enriched_beatport_id IS NULL
                 AND artist IS NOT NULL AND title IS NOT NULL
               ORDER BY id""",
        ).fetchall()


def mark_sync_miss(row_id: int, outcome: str, db_path: Path | None = None) -> None:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE sync_tracks SET enrich_outcome = ? WHERE id = ?",
            (outcome, row_id),
        )


def mark_sync_enriched(row_id: int, beatport_id: int, db_path: Path | None = None) -> None:
    with _conn(db_path) as con:
        con.execute(
            "UPDATE sync_tracks SET enrich_outcome = 'found', enriched_beatport_id = ? WHERE id = ?",
            (beatport_id, row_id),
        )


def mark_sync_duplicate(row_id: int, beatport_id: int, db_path: Path | None = None) -> None:
    """A track whose base title was already enriched — link it to the existing beatport_id."""
    with _conn(db_path) as con:
        con.execute(
            "UPDATE sync_tracks SET enrich_outcome = 'duplicate', enriched_beatport_id = ? WHERE id = ?",
            (beatport_id, row_id),
        )


def get_sync_track(row_id: int, db_path: Path | None = None) -> Optional[sqlite3.Row]:
    with _conn(db_path) as con:
        return con.execute("SELECT * FROM sync_tracks WHERE id = ?", (row_id,)).fetchone()


def get_tracks_by_ids(ids: list[int], db_path: Path | None = None) -> list[sqlite3.Row]:
    """Fetch sync_tracks rows by id, returned in the given id order."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with _conn(db_path) as con:
        rows = con.execute(
            f"SELECT * FROM sync_tracks WHERE id IN ({placeholders})", ids
        ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def run_select(sql: str, db_path: Path | None = None) -> list[sqlite3.Row]:
    """Run a user SELECT (push selection). Read-only guard only.

    To push a captured playlist back, join membership, e.g.:
        SELECT t.* FROM sync_tracks t
        JOIN sync_playlist_tracks m ON m.sync_track_id = t.id
        WHERE m.app = 'spotify' AND m.native_playlist_id = '<id>'
        ORDER BY m.position
    """
    s = sql.strip()
    if not (s.lower().startswith("select ") or s.lower().startswith("with ")):
        raise ValueError("Query must start with SELECT or WITH")
    with _conn(db_path) as con:
        return con.execute(s).fetchall()


# ── Auth cache (per-service refresh tokens, e.g. Spotify) ───────────────────────


def get_auth(service: str, db_path: Path | None = None) -> Optional[str]:
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT token FROM auth_cache WHERE service = ?", (service,)
        ).fetchone()
    return row["token"] if row else None


def set_auth(service: str, token: str, expires_at: Optional[str] = None,
             db_path: Path | None = None) -> None:
    with _conn(db_path) as con:
        con.execute(
            """INSERT INTO auth_cache (service, token, captured_at, expires_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(service) DO UPDATE SET
                 token=excluded.token, captured_at=excluded.captured_at,
                 expires_at=excluded.expires_at""",
            (service, token, _now(), expires_at),
        )


# ── Cursors (incremental --library capture) ─────────────────────────────────────


def get_cursor(key: str, db_path: Path | None = None) -> Optional[str]:
    """Return the stored cursor value for key, or None if not set."""
    with _conn(db_path) as con:
        row = con.execute("SELECT value FROM cursors WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_cursor(key: str, value: str, db_path: Path | None = None) -> None:
    with _conn(db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO cursors (key, value) VALUES (?, ?)", (key, value)
        )
