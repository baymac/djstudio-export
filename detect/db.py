"""SQLite persistence for track detection — all data in the unified dj.db."""
from __future__ import annotations

import re as _re
import sqlite3
from datetime import datetime, timezone

from paths import DB_PATH

# Tracks where artist or title is literally "ID" (DJ shorthand for "I don't know
# this track") are stored but never fuzzy-matched on Beatport — marked 'secret'.
_SECRET_ID_RE = _re.compile(r"^ID$", _re.IGNORECASE)


def is_id_placeholder(text: str | None) -> bool:
    """True when text is exactly 'ID' (case-insensitive) — an unknown-track sentinel."""
    return bool(text and _SECRET_ID_RE.match(text.strip()))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate() -> None:
    """Create all detect tables. Safe to run multiple times."""
    with _connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS detected_tracks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                artist          TEXT,
                title           TEXT,
                shazam_key      TEXT,
                apple_music_id  TEXT,
                apple_music_url TEXT,
                source          TEXT,
                synced_at       TEXT NOT NULL,
                enrich_outcome  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_detected_shazam ON detected_tracks(shazam_key);

            CREATE TABLE IF NOT EXISTS sessions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                type                  TEXT    NOT NULL,
                url                   TEXT    NOT NULL,
                title                 TEXT,
                uploader              TEXT,
                caption               TEXT,
                duration_seconds      INTEGER,
                last_scanned_position INTEGER,
                started_at            TEXT    NOT NULL,
                ended_at              TEXT,
                UNIQUE(url)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(type);

            CREATE TABLE IF NOT EXISTS track_sessions (
                track_id   INTEGER NOT NULL REFERENCES detected_tracks(id) ON DELETE CASCADE,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                position   INTEGER,
                PRIMARY KEY (track_id, session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ts_session ON track_sessions(session_id);

            CREATE TABLE IF NOT EXISTS gem_scans (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                source          TEXT    NOT NULL,
                genre           TEXT    NOT NULL,
                requested_count INTEGER,
                max_age_days    INTEGER,
                found_count     INTEGER DEFAULT 0,
                created_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_gem_scans_session ON gem_scans(session_id);

            CREATE TABLE IF NOT EXISTS gem_tracks (
                detected_track_id INTEGER NOT NULL REFERENCES detected_tracks(id) ON DELETE CASCADE,
                gem_scan_id       INTEGER NOT NULL REFERENCES gem_scans(id) ON DELETE CASCADE,
                source            TEXT    NOT NULL,
                url               TEXT,
                release_date      TEXT,
                plays             INTEGER,
                popularity        INTEGER,
                PRIMARY KEY (detected_track_id, gem_scan_id)
            );

            CREATE INDEX IF NOT EXISTS idx_gem_tracks_fade ON gem_tracks(source, release_date);

            CREATE TABLE IF NOT EXISTS rejected_gems (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source       TEXT NOT NULL,
                artist       TEXT,
                title        TEXT,
                url          TEXT,
                release_date TEXT,
                rejected_at  TEXT NOT NULL,
                UNIQUE(source, artist, title)
            );

            CREATE INDEX IF NOT EXISTS idx_rejected_gems_fade ON rejected_gems(source, release_date);

            CREATE TABLE IF NOT EXISTS enriched_tracks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_track_id INTEGER UNIQUE REFERENCES detected_tracks(id) ON DELETE CASCADE,
                beatport_id       INTEGER NOT NULL,
                beatport_link     TEXT,
                bpm               REAL,
                key               TEXT,
                genre             TEXT,
                release_date      TEXT,
                apple_music_url   TEXT,
                artist            TEXT,
                title             TEXT,
                enriched_at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_enriched_detected ON enriched_tracks(detected_track_id);
            CREATE INDEX IF NOT EXISTS idx_enriched_beatport_id ON enriched_tracks(beatport_id);

            CREATE TABLE IF NOT EXISTS beatport_playlists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                beatport_id INTEGER NOT NULL UNIQUE,
                name        TEXT    NOT NULL,
                synced_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS beatport_playlist_tracks (
                playlist_id       INTEGER NOT NULL REFERENCES beatport_playlists(id) ON DELETE CASCADE,
                enriched_track_id INTEGER NOT NULL REFERENCES enriched_tracks(id) ON DELETE CASCADE,
                PRIMARY KEY (playlist_id, enriched_track_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bpt_playlist ON beatport_playlist_tracks(playlist_id);
            CREATE INDEX IF NOT EXISTS idx_bpt_track ON beatport_playlist_tracks(enriched_track_id);

            CREATE TABLE IF NOT EXISTS enrich_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                seen        INTEGER DEFAULT 0,
                found       INTEGER DEFAULT 0,
                not_found   INTEGER DEFAULT 0,
                fuzzy_miss  INTEGER DEFAULT 0,
                status      TEXT
            );

            CREATE TABLE IF NOT EXISTS deleted_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL,
                type         TEXT    NOT NULL,
                url          TEXT    NOT NULL,
                title        TEXT,
                uploader     TEXT,
                track_count  INTEGER NOT NULL DEFAULT 0,
                started_at   TEXT,
                deleted_at   TEXT    NOT NULL
            );
        """)
        try:
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_detected_shazam_key
                ON detected_tracks(shazam_key) WHERE shazam_key IS NOT NULL
            """)
        except Exception:
            pass

        # ── enriched_tracks_analysis: DJ Studio + rekordbox analysis only ─────
        # Lean linking-table keyed on beatport_id. All Beatport-derived fields
        # (artist/title/bpm/key/genre/mix_name/label/...) live on `enriched_tracks`
        # and are joined in at query time.
        # A row exists in this table only after `dj enrich analyse` has
        # populated it. The SDK driver writes directly here — DJ
        # Studio's filesystem is never touched.
        con.execute("""
            CREATE TABLE IF NOT EXISTS enriched_tracks_analysis (
                beatport_id           INTEGER PRIMARY KEY,
                -- DJ Studio (from SDK output via studio-analyse)
                mik_key               TEXT,
                mik_nrg               REAL,
                vocals                TEXT,
                drums                 TEXT,
                melody                TEXT,
                mik_key_secondary     TEXT,
                mik_key_confidence    REAL,
                tempo_precise         REAL,
                duration_sec          REAL,
                cue_points_count      INTEGER,
                vocals_avg            REAL,
                drums_avg             REAL,
                bass_avg              REAL,
                melody_avg            REAL,
                vocals_peak           REAL,
                drums_peak            REAL,
                bass_peak             REAL,
                melody_peak           REAL,
                analysis_json         TEXT,
                -- Rekordbox round-trip
                rk_analysis_json      TEXT,
                -- Per-stage timestamps (skip rules + idempotence)
                dj_studio_at          TEXT,
                rekordbox_export_at   TEXT,
                rekordbox_analysis_at TEXT
            )
        """)

        # Per-slice Shazam scan log — one row per (session, position) attempt.
        # status: 'found' | 'duplicate' | 'not_recognized' | 'timeout' | 'error' | 'slice_failed'
        con.execute("""
            CREATE TABLE IF NOT EXISTS shazam_slices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                position        INTEGER NOT NULL,
                status          TEXT    NOT NULL,
                artist          TEXT,
                title           TEXT,
                shazam_key      TEXT,
                apple_music_url TEXT,
                scanned_at      TEXT    NOT NULL,
                UNIQUE(session_id, position)
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_shazam_slices_session
            ON shazam_slices(session_id)
        """)

        # ── DJ sets (any curated tracklist) ───────────────────────────────────
        # A "set" is any named tracklist regardless of where it lives — a
        # Beatport chart, a Mixcloud upload, an impromptu rekordbox set, etc.
        # Identity is (name, type); `type` names the platform/context. One row
        # per set; the ordered track list lives in the dj_set_tracks junction.
        #
        # Modelled like beatport_playlists/_tracks, but the junction keys on
        # beatport_id (not enriched_tracks.id) — same choice as
        # enriched_tracks_analysis, so the full row is a query-time join
        # (dj_set_tracks JOIN enriched_tracks USING(beatport_id)). beatport_id is
        # our canonical track identity across the library; no hard FK to
        # enriched_tracks because its UNIQUE(beatport_id) index is created
        # conditionally, so we keep beatport_id as a plain indexed column.
        con.executescript("""
            CREATE TABLE IF NOT EXISTS dj_sets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                type       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL,
                UNIQUE(name, type)
            );

            CREATE TABLE IF NOT EXISTS dj_set_tracks (
                set_id      INTEGER NOT NULL REFERENCES dj_sets(id) ON DELETE CASCADE,
                beatport_id INTEGER NOT NULL,
                position    INTEGER NOT NULL,
                added_at    TEXT    NOT NULL,
                PRIMARY KEY (set_id, beatport_id)
            );

            -- "which sets is this track in?" + "how many sets contain it?":
            -- leading beatport_id so both are index-only lookups.
            CREATE INDEX IF NOT EXISTS idx_dj_set_tracks_track
                ON dj_set_tracks(beatport_id);
            -- one track per position within a set (preserves tracklist order).
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dj_set_tracks_pos
                ON dj_set_tracks(set_id, position);
        """)

        # Additive migration: full Beatport catalog detail on the lean table
        # (added after enriched_tracks shipped).
        for _col, _typ in _BEATPORT_EXTRAS_COLS:
            _add_column_if_missing(con, "enriched_tracks", _col, _typ)

        # Additive migration: duplicate count on enrich_runs.
        _add_column_if_missing(con, "enrich_runs", "duplicate", "INTEGER DEFAULT 0")

        # Additive migration: build provenance for sets curated by build_set.py
        # (mood, duration, count, genres, date filter, archetype curve) as JSON.
        # `dj_sets.type` carries the archetype key; this carries everything else.
        _add_column_if_missing(con, "dj_sets", "params_json", "TEXT")

        # Additive migration: flip the FK direction so many detected_tracks can
        # share one enriched_tracks row without copying data.
        _add_column_if_missing(con, "detected_tracks", "enriched_track_id", "INTEGER REFERENCES enriched_tracks(id)")
        # UNIQUE index on beatport_id — enforces one enriched row per Beatport track.
        # (Safe only after dedupe_enriched_tracks has been run; try/except guards.)
        try:
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_enriched_beatport_unique "
                "ON enriched_tracks(beatport_id)"
            )
        except sqlite3.OperationalError:
            pass
        # Populate enriched_track_id for existing rows from the old detected_track_id column.
        con.execute("""
            UPDATE detected_tracks
            SET enriched_track_id = (
                SELECT et.id FROM enriched_tracks et
                WHERE et.detected_track_id = detected_tracks.id
            )
            WHERE enriched_track_id IS NULL
        """)

        # Static Beatport key-name → Camelot lookup table.
        con.execute("""
            CREATE TABLE IF NOT EXISTS key_map (
                beatport_key TEXT PRIMARY KEY,
                camelot      TEXT NOT NULL
            )
        """)
        con.executemany(
            "INSERT OR IGNORE INTO key_map (beatport_key, camelot) VALUES (?, ?)",
            _KEY_MAP_ROWS,
        )


# Full Beatport text key → Camelot wheel.  Covers all enharmonic spellings.
_KEY_MAP_ROWS = [
    # ── Major (B suffix) ──────────────────────────────────────────────────────
    ("B Major",   "1B"),
    ("F# Major",  "2B"), ("Gb Major",  "2B"),
    ("Db Major",  "3B"), ("C# Major",  "3B"),
    ("Ab Major",  "4B"), ("G# Major",  "4B"),
    ("Eb Major",  "5B"), ("D# Major",  "5B"),
    ("Bb Major",  "6B"), ("A# Major",  "6B"),
    ("F Major",   "7B"),
    ("C Major",   "8B"),
    ("G Major",   "9B"),
    ("D Major",   "10B"),
    ("A Major",   "11B"),
    ("E Major",   "12B"),
    # ── Minor (A suffix) ──────────────────────────────────────────────────────
    ("Ab Minor",  "1A"), ("G# Minor",  "1A"),
    ("Eb Minor",  "2A"), ("D# Minor",  "2A"),
    ("Bb Minor",  "3A"), ("A# Minor",  "3A"),
    ("F Minor",   "4A"),
    ("C Minor",   "5A"),
    ("G Minor",   "6A"),
    ("D Minor",   "7A"),
    ("A Minor",   "8A"),
    ("E Minor",   "9A"),
    ("B Minor",   "10A"),
    ("F# Minor",  "11A"), ("Gb Minor", "11A"),
    ("Db Minor",  "12A"), ("C# Minor", "12A"),
]


def _add_column_if_missing(con: sqlite3.Connection, table: str, col: str, typ: str) -> None:
    """ALTER TABLE ADD COLUMN if not already present. Idempotent."""
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass


_BEATPORT_EXTRAS_COLS = (
    ("mix_name", "TEXT"),
    ("label", "TEXT"),
    ("catalog_number", "TEXT"),
    ("isrc", "TEXT"),
    ("sub_genre", "TEXT"),
    ("length_ms", "INTEGER"),
)


# ── Unified session helpers ───────────────────────────────────────────────────


def create_session(
    type_: str,
    url: str,
    title: str,
    uploader: str | None = None,
    duration_seconds: int | None = None,
    caption: str | None = None,
) -> int:
    """Insert or return existing session for this URL. Returns session id."""
    with _connect() as con:
        con.execute(
            """INSERT OR IGNORE INTO sessions
               (type, url, title, uploader, duration_seconds, caption, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (type_, url, title, uploader, duration_seconds, caption, _now()),
        )
        row = con.execute("SELECT id FROM sessions WHERE url = ?", (url,)).fetchone()
        return row["id"]


def end_session(session_id: int) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?", (_now(), session_id)
        )


def update_session_progress(session_id: int, position: int) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE sessions SET last_scanned_position = ? WHERE id = ?",
            (position, session_id),
        )


# ── Gem scans ─────────────────────────────────────────────────────────────────


def create_gem_scan(
    session_id: int,
    source: str,
    genre: str,
    requested_count: int | None,
    max_age_days: int | None,
) -> int:
    """Insert a gem_scans row for one `detect gems` run. Returns its id."""
    with _connect() as con:
        cur = con.execute(
            """INSERT INTO gem_scans
               (session_id, source, genre, requested_count, max_age_days, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, source, genre, requested_count, max_age_days, _now()),
        )
        return cur.lastrowid


def finish_gem_scan(gem_scan_id: int, found_count: int) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE gem_scans SET found_count = ? WHERE id = ?",
            (found_count, gem_scan_id),
        )


def insert_gem_track(
    detected_track_id: int,
    gem_scan_id: int,
    source: str,
    url: str | None,
    release_date: str | None,
    plays: int | None = None,
    popularity: int | None = None,
) -> None:
    """Record gems-specific per-track metadata. Idempotent per (track, scan)."""
    with _connect() as con:
        con.execute(
            """INSERT OR IGNORE INTO gem_tracks
               (detected_track_id, gem_scan_id, source, url, release_date, plays, popularity)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (detected_track_id, gem_scan_id, source, url, release_date, plays, popularity),
        )


def seen_gem_keys(source: str, cutoff_date: str) -> set[tuple[str, str]]:
    """Return (artist, title) keys of prior gems on `source` that could recur.

    Gems released before `cutoff_date` (YYYY-MM-DD) are "faded" — they can't
    appear in a search bounded by that cutoff, so they're dropped from the
    comparison set. NULL release dates can't be fade-proven, so they're kept.
    """
    with _connect() as con:
        rows = con.execute(
            """SELECT d.artist AS artist, d.title AS title
               FROM gem_tracks gt
               JOIN detected_tracks d ON d.id = gt.detected_track_id
               WHERE gt.source = ?
                 AND (gt.release_date IS NULL OR gt.release_date >= ?)""",
            (source, cutoff_date),
        ).fetchall()
    return {
        ((r["artist"] or "").strip().lower(), (r["title"] or "").strip().lower())
        for r in rows
    }


def insert_rejected_gem(
    source: str,
    artist: str,
    title: str,
    url: str | None = None,
    release_date: str | None = None,
) -> None:
    """Record a gem the user rejected during review so it won't resurface."""
    with _connect() as con:
        con.execute(
            """INSERT OR IGNORE INTO rejected_gems
               (source, artist, title, url, release_date, rejected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, artist, title, url, release_date, _now()),
        )


def seen_rejected_gem_keys(source: str, cutoff_date: str) -> set[tuple[str, str]]:
    """Return (artist, title) keys of rejected gems on `source` that could recur.

    Same fade rule as `seen_gem_keys`: rejections of tracks released before
    `cutoff_date` can't reappear in a search bounded by that cutoff.
    """
    with _connect() as con:
        rows = con.execute(
            """SELECT artist, title FROM rejected_gems
               WHERE source = ?
                 AND (release_date IS NULL OR release_date >= ?)""",
            (source, cutoff_date),
        ).fetchall()
    return {
        ((r["artist"] or "").strip().lower(), (r["title"] or "").strip().lower())
        for r in rows
    }


def upsert_shazam_slice(
    session_id: int,
    position: int,
    status: str,
    *,
    artist: str | None = None,
    title: str | None = None,
    shazam_key: str | None = None,
    apple_music_url: str | None = None,
) -> None:
    """Record one Shazam slice scan result. Safe to call multiple times for same position."""
    with _connect() as con:
        con.execute(
            """INSERT INTO shazam_slices
               (session_id, position, status, artist, title, shazam_key, apple_music_url, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_id, position) DO UPDATE SET
                   status=excluded.status, artist=excluded.artist, title=excluded.title,
                   shazam_key=excluded.shazam_key, apple_music_url=excluded.apple_music_url,
                   scanned_at=excluded.scanned_at""",
            (session_id, position, status, artist, title, shazam_key, apple_music_url, _now()),
        )


def find_session(url: str) -> sqlite3.Row | None:
    with _connect() as con:
        return con.execute("SELECT * FROM sessions WHERE url = ?", (url,)).fetchone()


def infer_last_position(session_id: int) -> int | None:
    with _connect() as con:
        row = con.execute(
            "SELECT MAX(ts.position) AS p FROM track_sessions ts WHERE ts.session_id = ?",
            (session_id,),
        ).fetchone()
        return row["p"] if row and row["p"] is not None else None


def delete_session(session_id: int) -> int:
    """Delete session; tracks exclusively belonging to it (no other sessions, no enrichment) are also deleted."""
    with _connect() as con:
        session = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        n = con.execute(
            "SELECT COUNT(*) FROM track_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        if session:
            con.execute(
                """INSERT INTO deleted_sessions
                   (session_id, type, url, title, uploader, track_count, started_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, session["type"], session["url"], session["title"],
                 session["uploader"], n, session["started_at"], _now()),
            )
        con.execute("""
            DELETE FROM detected_tracks
            WHERE id IN (SELECT track_id FROM track_sessions WHERE session_id = ?)
              AND id NOT IN (SELECT track_id FROM track_sessions WHERE session_id != ?)
              AND enriched_track_id IS NULL
              AND source != 'beatport'
        """, (session_id, session_id))
        con.execute("DELETE FROM track_sessions WHERE session_id = ?", (session_id,))
        con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return n


def remove_tracks_from_session(session_id: int, track_ids: list[int]) -> list[int]:
    """Unlink specific tracks from a session and delete them if they have no other home.

    A track is deleted from detected_tracks if:
    - it belongs only to this session (no other track_sessions row)
    - it hasn't been enriched (no enriched_tracks row)
    - its source is not 'beatport'

    Returns the list of track_ids that were actually deleted from detected_tracks.
    """
    if not track_ids:
        return []
    placeholders = ",".join("?" * len(track_ids))
    deleted = []
    with _connect() as con:
        # Find which of the requested track_ids can be fully deleted
        rows = con.execute(
            f"""SELECT id FROM detected_tracks
                WHERE id IN ({placeholders})
                  AND id NOT IN (
                      SELECT track_id FROM track_sessions
                      WHERE session_id != ? AND track_id IN ({placeholders})
                  )
                  AND enriched_track_id IS NULL
                  AND source != 'beatport'""",
            (*track_ids, session_id, *track_ids),
        ).fetchall()
        deletable = {r["id"] for r in rows}
        for tid in track_ids:
            con.execute(
                "DELETE FROM track_sessions WHERE track_id = ? AND session_id = ?",
                (tid, session_id),
            )
            if tid in deletable:
                con.execute("DELETE FROM detected_tracks WHERE id = ?", (tid,))
                deleted.append(tid)
    return deleted


def list_sessions(type_: str, limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT s.*, COUNT(ts.track_id) AS track_count
               FROM sessions s
               LEFT JOIN track_sessions ts ON ts.session_id = s.id
               WHERE s.type = ?
               GROUP BY s.id
               ORDER BY s.started_at DESC
               LIMIT ?""",
            (type_, limit),
        ).fetchall()


# ── Track helpers ─────────────────────────────────────────────────────────────


def insert_track(
    track: dict,
    *,
    source: str,
    session_id: int | None = None,
) -> int:
    """Insert or find a detected track (globally deduped). Link to session if provided."""
    with _connect() as con:
        shazam_key = track.get("shazam_key")
        artist     = track.get("artist")
        title      = track.get("title")
        position   = track.get("position")

        existing = None
        if shazam_key:
            existing = con.execute(
                "SELECT id FROM detected_tracks WHERE shazam_key = ?", (shazam_key,)
            ).fetchone()
        if not existing and artist and title:
            existing = con.execute(
                "SELECT id FROM detected_tracks "
                "WHERE artist = ? AND title = ? AND shazam_key IS NULL",
                (artist, title),
            ).fetchone()

        if existing:
            track_id = existing["id"]
        else:
            outcome = "secret" if (is_id_placeholder(artist) or is_id_placeholder(title)) else None
            cur = con.execute(
                """INSERT INTO detected_tracks
                   (artist, title, shazam_key, apple_music_id, apple_music_url, source, synced_at, enrich_outcome)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (artist, title, shazam_key,
                 track.get("apple_music_id"), track.get("apple_music_url"),
                 source, _now(), outcome),
            )
            track_id = cur.lastrowid

        if session_id is not None:
            con.execute(
                "INSERT OR IGNORE INTO track_sessions (track_id, session_id, position) "
                "VALUES (?, ?, ?)",
                (track_id, session_id, position),
            )

        return track_id


def insert_tracks(
    tracks: list[dict],
    *,
    source: str,
    session_id: int | None = None,
) -> None:
    for t in tracks:
        insert_track(t, source=source, session_id=session_id)


def list_tracks(limit: int = 50) -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT * FROM detected_tracks
               WHERE enrich_outcome IS NULL OR enrich_outcome != 'duplicate'
               ORDER BY synced_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def tracks_for_session(session_id: int) -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT d.*, ts.position
               FROM detected_tracks d
               JOIN track_sessions ts ON ts.track_id = d.id
               WHERE ts.session_id = ?
               ORDER BY ts.position, d.id""",
            (session_id,),
        ).fetchall()


def tracks_for_session_enriched(session_id: int) -> list[sqlite3.Row]:
    """All tracks for a session with enrichment data where available.

    Duplicate-outcome tracks (same beatport_id found via a different detected_track)
    are resolved by falling back to an artist+title match in enriched_tracks so the
    full BPM/key/etc. are still returned.
    """
    with _connect() as con:
        return con.execute(
            """SELECT d.id, ts.position, d.enrich_outcome,
                      COALESCE(ed.artist, ei.artist, d.artist) AS artist,
                      COALESCE(ed.title,  ei.title,  d.title)  AS title,
                      COALESCE(ed.apple_music_url, d.apple_music_url) AS apple_music_url,
                      COALESCE(ed.beatport_id,   ei.beatport_id)   AS beatport_id,
                      COALESCE(ed.beatport_link, ei.beatport_link) AS beatport_link,
                      COALESCE(ed.bpm,           ei.bpm)           AS bpm,
                      COALESCE(ed.key,           ei.key)           AS key,
                      COALESCE(ed.genre,         ei.genre)         AS genre,
                      COALESCE(ed.release_date,  ei.release_date)  AS release_date,
                      a.mik_key  AS mik_key,
                      a.mik_nrg  AS mik_nrg,
                      a.vocals   AS vocals,
                      a.drums    AS drums,
                      a.melody   AS melody
               FROM detected_tracks d
               JOIN track_sessions ts ON ts.track_id = d.id
               LEFT JOIN enriched_tracks ed ON ed.id = d.enriched_track_id
               LEFT JOIN enriched_tracks ei ON ei.id = (
                   SELECT e2.id FROM enriched_tracks e2
                   WHERE LOWER(e2.artist) = LOWER(d.artist)
                     AND LOWER(e2.title)  = LOWER(d.title)
                   LIMIT 1
               )
               LEFT JOIN enriched_tracks_analysis a
                      ON a.beatport_id = COALESCE(ed.beatport_id, ei.beatport_id)
               WHERE ts.session_id = ?
               ORDER BY ts.position, d.id""",
            (session_id,),
        ).fetchall()


# ── Enrichment helpers ────────────────────────────────────────────────────────


def get_unenriched_tracks() -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT * FROM detected_tracks
               WHERE enriched_track_id IS NULL
                 AND enrich_outcome IS NULL
                 AND artist IS NOT NULL AND title IS NOT NULL
               ORDER BY id""",
        ).fetchall()


def get_retry_tracks() -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT * FROM detected_tracks
               WHERE enrich_outcome IN ('not_found', 'fuzzy_miss')
                 AND enriched_track_id IS NULL
                 AND artist IS NOT NULL AND title IS NOT NULL
               ORDER BY id""",
        ).fetchall()


def list_enriched_tracks(limit: int = 50, playlist_name: str | None = None) -> list[sqlite3.Row]:
    with _connect() as con:
        if playlist_name:
            return con.execute(
                """SELECT e.artist, e.title, e.beatport_id, e.beatport_link,
                          e.bpm, e.key, e.genre, e.release_date, e.apple_music_url,
                          a.mik_key, a.mik_nrg, a.vocals, a.drums, a.melody,
                          e.enriched_at
                   FROM enriched_tracks e
                   JOIN beatport_playlist_tracks bpt ON bpt.enriched_track_id = e.id
                   JOIN beatport_playlists bp ON bp.id = bpt.playlist_id
                   LEFT JOIN enriched_tracks_analysis a ON a.beatport_id = e.beatport_id
                   WHERE bp.name = ?
                   ORDER BY e.enriched_at DESC, e.id DESC
                   LIMIT ?""",
                (playlist_name, limit),
            ).fetchall()
        return con.execute(
            """SELECT e.artist, e.title, e.beatport_id, e.beatport_link,
                      e.bpm, e.key, e.genre, e.release_date, e.apple_music_url,
                      a.mik_key, a.mik_nrg, a.vocals, a.drums, a.melody,
                      e.enriched_at
               FROM enriched_tracks e
               LEFT JOIN enriched_tracks_analysis a ON a.beatport_id = e.beatport_id
               ORDER BY e.enriched_at DESC, e.id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()


def upsert_enriched(detected_track_id: int, meta: dict, extras: dict | None = None) -> None:
    """Insert or update one row in `enriched_tracks`, then link detected_tracks.enriched_track_id.

    `meta` carries the search-result fields (bpm/key/genre/release_date/beatport_link).
    `extras` (optional) carries the full-track-detail fields fetched from
    `/v4/catalog/tracks/{id}/`: mix_name, label, catalog_number, isrc, sub_genre,
    length_ms. NULL extras leave existing values intact (COALESCE).

    Multiple detected_tracks rows may point to the same enriched_tracks row (e.g.
    a remix and the base version that both resolved to the same beatport_id). The
    enriched row is keyed on beatport_id; detected_tracks.enriched_track_id is the
    link. No data is copied — all variants share one canonical row.
    """
    extras = extras or {}
    with _connect() as con:
        beatport_id = meta.get("beatport_id")

        row = con.execute(
            "SELECT artist, title, apple_music_url FROM detected_tracks WHERE id = ?",
            (detected_track_id,),
        ).fetchone()
        artist = row["artist"] if row else None
        title = row["title"] if row else None
        apple_url = row["apple_music_url"] if row else None

        _upsert_enriched_row(con, meta, extras, artist, title, apple_url)
        # Link this detected track to the enriched row (or the pre-existing one
        # for the same beatport_id that came in via sync-beatport).
        con.execute("""
            UPDATE detected_tracks
            SET enriched_track_id = (SELECT id FROM enriched_tracks WHERE beatport_id = ?)
            WHERE id = ?
        """, (beatport_id, detected_track_id))


def upsert_enriched_values(
    meta: dict,
    artist: str | None,
    title: str | None,
    *,
    extras: dict | None = None,
    apple_url: str | None = None,
) -> None:
    """Upsert one `enriched_tracks` row from explicit values (no detected_tracks link).

    Used by `dj enrich --sync`, whose candidate rows live in `sync_tracks`, not
    `detected_tracks`. Same dedup-by-beatport_id semantics as `upsert_enriched`;
    the sync adapter records the back-link (sync_tracks.enriched_beatport_id) itself.
    """
    with _connect() as con:
        _upsert_enriched_row(con, meta, extras or {}, artist, title, apple_url)


def _upsert_enriched_row(con, meta: dict, extras: dict, artist, title, apple_url) -> None:
    """INSERT … ON CONFLICT(beatport_id) the enriched_tracks row. Single-sourced SQL."""
    con.execute(
        """INSERT INTO enriched_tracks
           (beatport_id, beatport_link, bpm, key, genre,
            release_date, apple_music_url, artist, title, enriched_at,
            mix_name, label, catalog_number, isrc, sub_genre, length_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(beatport_id) DO UPDATE SET
             beatport_link   = excluded.beatport_link,
             bpm             = excluded.bpm,
             key             = excluded.key,
             genre           = excluded.genre,
             release_date    = excluded.release_date,
             apple_music_url = COALESCE(excluded.apple_music_url, enriched_tracks.apple_music_url),
             artist          = COALESCE(excluded.artist, enriched_tracks.artist),
             title           = COALESCE(excluded.title, enriched_tracks.title),
             enriched_at     = excluded.enriched_at,
             mix_name        = COALESCE(excluded.mix_name,       enriched_tracks.mix_name),
             label           = COALESCE(excluded.label,          enriched_tracks.label),
             catalog_number  = COALESCE(excluded.catalog_number, enriched_tracks.catalog_number),
             isrc            = COALESCE(excluded.isrc,           enriched_tracks.isrc),
             sub_genre       = COALESCE(excluded.sub_genre,      enriched_tracks.sub_genre),
             length_ms       = COALESCE(excluded.length_ms,      enriched_tracks.length_ms)""",
        (
            meta.get("beatport_id"),
            meta.get("beatport_link"),
            meta.get("bpm"),
            meta.get("key"),
            meta.get("genre"),
            meta.get("release_date"),
            apple_url,
            artist,
            title,
            _now(),
            extras.get("mix_name"),
            extras.get("label"),
            extras.get("catalog_number"),
            extras.get("isrc"),
            extras.get("sub_genre"),
            extras.get("length_ms"),
        ),
    )


def link_detected_to_enriched(detected_track_id: int, beatport_id: int) -> bool:
    """Point detected_tracks.enriched_track_id at an existing enriched row.

    Used when a remix/variant is deduplicated against an already-enriched base
    title — no data copy needed, just a FK link so JOINs on enriched_track_id work.
    Returns True if the enriched row was found and linked, False otherwise.
    """
    with _connect() as con:
        row = con.execute(
            "SELECT id FROM enriched_tracks WHERE beatport_id = ?", (beatport_id,)
        ).fetchone()
        if not row:
            return False
        con.execute(
            "UPDATE detected_tracks SET enriched_track_id = ? WHERE id = ?",
            (row["id"], detected_track_id),
        )
        return True


def get_enriched_artist_titles() -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute("SELECT artist, title, beatport_id FROM enriched_tracks").fetchall()


def mark_enrich_miss(detected_track_id: int, outcome: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE detected_tracks SET enrich_outcome = ? WHERE id = ?",
            (outcome, detected_track_id),
        )


def mark_enrich_secret(detected_track_id: int) -> None:
    """Mark a track as a secret/ID placeholder — skip fuzzy matching."""
    with _connect() as con:
        con.execute(
            "UPDATE detected_tracks SET enrich_outcome = 'secret' WHERE id = ?",
            (detected_track_id,),
        )


def count_secret_tracks() -> int:
    """Count detected tracks that are ID placeholders (enrich_outcome='secret')."""
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM detected_tracks WHERE enrich_outcome = 'secret'"
        ).fetchone()
        return row[0] if row else 0


def start_enrich_run() -> int:
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO enrich_runs (started_at, status) VALUES (?, 'running')", (_now(),)
        )
        return cur.lastrowid


def finish_enrich_run(
    run_id: int, seen: int, found: int, not_found: int, fuzzy_miss: int, duplicate: int = 0
) -> None:
    with _connect() as con:
        con.execute(
            """UPDATE enrich_runs
               SET finished_at=?, seen=?, found=?, not_found=?, fuzzy_miss=?, duplicate=?, status='done'
               WHERE id=?""",
            (_now(), seen, found, not_found, fuzzy_miss, duplicate, run_id),
        )


def list_enrich_runs(limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as con:
        return con.execute(
            """SELECT * FROM enrich_runs ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def upsert_beatport_playlist(beatport_id: int, name: str) -> int:
    """Upsert a Beatport playlist record. Returns the local row id."""
    with _connect() as con:
        con.execute(
            """INSERT INTO beatport_playlists (beatport_id, name, synced_at)
               VALUES (?, ?, ?)
               ON CONFLICT(beatport_id) DO UPDATE SET name=excluded.name, synced_at=excluded.synced_at""",
            (beatport_id, name, _now()),
        )
        row = con.execute(
            "SELECT id FROM beatport_playlists WHERE beatport_id = ?", (beatport_id,)
        ).fetchone()
        return row["id"]


def list_beatport_playlists() -> list[sqlite3.Row]:
    """Synced Beatport playlists with their local track counts (for `playlist list`)."""
    with _connect() as con:
        return con.execute(
            """SELECT bp.beatport_id, bp.name, COUNT(bpt.enriched_track_id) AS track_count
               FROM beatport_playlists bp
               LEFT JOIN beatport_playlist_tracks bpt ON bpt.playlist_id = bp.id
               GROUP BY bp.id
               ORDER BY bp.name""",
        ).fetchall()


def beatport_track_ids_in_playlist(beatport_id: int) -> list[int]:
    """Catalog track_ids for one captured Beatport playlist (for `playlist push` restore).

    The junction has no position column, so order falls back to insertion order
    (enriched_track_id). Returns the Beatport catalog ids to re-add on recreation.
    """
    with _connect() as con:
        rows = con.execute(
            """SELECT e.beatport_id
               FROM beatport_playlists bp
               JOIN beatport_playlist_tracks bpt ON bpt.playlist_id = bp.id
               JOIN enriched_tracks e ON e.id = bpt.enriched_track_id
               WHERE bp.beatport_id = ? AND e.beatport_id IS NOT NULL
               ORDER BY bpt.enriched_track_id""",
            (beatport_id,),
        ).fetchall()
    return [r["beatport_id"] for r in rows]


def insert_beatport_track(
    artist: str,
    title: str,
    beatport_link: str,
    meta: dict,
    extras: dict | None = None,
    playlist_id: int | None = None,
) -> bool:
    """Upsert a track from a Beatport playlist into enriched_tracks.

    `meta` carries the basic fields (bpm/key/genre/release_date).
    `extras` (optional) carries the full-track-detail fields (mix_name, label,
    catalog_number, isrc, sub_genre, length_ms) extracted from the same playlist
    response — Beatport returns those inline, no extra HTTP call needed.

    Writes artist/title directly — no detected_tracks row is created.
    Returns True if a new enriched_tracks row was created OR a new playlist link was added.
    """
    extras = extras or {}
    beatport_id = meta.get("beatport_id")
    with _connect() as con:
        row = con.execute(
            "SELECT id FROM enriched_tracks WHERE beatport_id = ?", (beatport_id,)
        ).fetchone()

        if row:
            enriched_id = row["id"]
            newly_inserted = False
            # Backfill extras on a pre-existing row if we have new values for it.
            con.execute(
                """UPDATE enriched_tracks SET
                     mix_name       = COALESCE(?, mix_name),
                     label          = COALESCE(?, label),
                     catalog_number = COALESCE(?, catalog_number),
                     isrc           = COALESCE(?, isrc),
                     sub_genre      = COALESCE(?, sub_genre),
                     length_ms      = COALESCE(?, length_ms)
                   WHERE id = ?""",
                (
                    extras.get("mix_name"),
                    extras.get("label"),
                    extras.get("catalog_number"),
                    extras.get("isrc"),
                    extras.get("sub_genre"),
                    extras.get("length_ms"),
                    enriched_id,
                ),
            )
        else:
            cur = con.execute(
                """INSERT INTO enriched_tracks
                   (beatport_id, beatport_link, bpm, key, genre,
                    release_date, artist, title, enriched_at,
                    mix_name, label, catalog_number, isrc, sub_genre, length_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    beatport_id, beatport_link,
                    meta.get("bpm"), meta.get("key"), meta.get("genre"),
                    meta.get("release_date"), artist, title, _now(),
                    extras.get("mix_name"),
                    extras.get("label"),
                    extras.get("catalog_number"),
                    extras.get("isrc"),
                    extras.get("sub_genre"),
                    extras.get("length_ms"),
                ),
            )
            enriched_id = cur.lastrowid
            newly_inserted = True

        newly_linked = False
        if playlist_id is not None:
            existing_link = con.execute(
                "SELECT 1 FROM beatport_playlist_tracks WHERE playlist_id = ? AND enriched_track_id = ?",
                (playlist_id, enriched_id),
            ).fetchone()
            if not existing_link:
                con.execute(
                    "INSERT OR IGNORE INTO beatport_playlist_tracks (playlist_id, enriched_track_id) VALUES (?, ?)",
                    (playlist_id, enriched_id),
                )
                newly_linked = True

        result = newly_inserted or newly_linked

    return result


ANALYSIS_TABLE = "enriched_tracks_analysis"


def get_studio_analyse_pending(*, force: bool = False) -> list[sqlite3.Row]:
    """All enriched tracks with a beatport_id. The caller (`dj enrich analyse`)
    filters client-side: tracks already in enriched_tracks_analysis are skipped
    unless `force=True`.

    Returns `length_ms` and `release_date` so the caller can:
    - pre-filter very short tracks (under ~30s) which can't produce reliable
      beats or stems anyway
    - skip pre-release tracks gracefully when the SDK rejects audio fetch
      (Beatport withholds audio until the release date)
    """
    with _connect() as con:
        return con.execute(
            """SELECT e.id, e.beatport_id, e.artist, e.title, e.bpm,
                      e.length_ms, e.release_date
                FROM enriched_tracks e
                WHERE e.beatport_id IS NOT NULL
                ORDER BY e.id"""
        ).fetchall()


def mark_pipeline_done(beatport_id: int, column: str) -> None:
    """Stamp a per-source completion column on enriched_tracks_analysis."""
    if column not in {"rekordbox_export_at", "rekordbox_analysis_at"}:
        raise ValueError(f"Unsupported column: {column}")
    with _connect() as con:
        con.execute(
            f"UPDATE {ANALYSIS_TABLE} SET {column} = ? WHERE beatport_id = ?",
            (_now(), beatport_id),
        )


def existing_analysis_beatport_ids() -> set[int]:
    """Return the set of beatport_ids that already have a row in
    enriched_tracks_analysis. Used by `dj enrich analyse` to skip
    work that was already done on a previous run."""
    with _connect() as con:
        return {r[0] for r in con.execute(
            f"SELECT beatport_id FROM {ANALYSIS_TABLE}"
        )}


_ANALYSIS_COLS = (
    "mik_key", "mik_nrg", "vocals", "drums", "melody",
    "mik_key_secondary", "mik_key_confidence",
    "tempo_precise", "duration_sec", "cue_points_count",
    "vocals_avg", "drums_avg", "bass_avg", "melody_avg",
    "vocals_peak", "drums_peak", "bass_peak", "melody_peak",
    "analysis_json",
)


def upsert_analysis(beatport_id: int, fields: dict) -> None:
    """Insert or update one row in enriched_tracks_analysis.

    Called by `dj enrich analyse` (the creation point) and any future
    stage that produces analysis data. Only the keys in `_ANALYSIS_COLS` are
    accepted; unknowns are ignored. `dj_studio_at` is stamped to NOW on the
    initial insert.
    """
    cols = {"beatport_id": beatport_id}
    for k in _ANALYSIS_COLS:
        if k in fields and fields[k] is not None:
            cols[k] = fields[k]
    cols["dj_studio_at"] = _now()

    columns = ", ".join(cols.keys())
    placeholders = ", ".join("?" * len(cols))
    update_pairs = [
        f"{k}=COALESCE(excluded.{k}, {ANALYSIS_TABLE}.{k})"
        for k in cols if k not in ("beatport_id", "dj_studio_at")
    ]
    on_conflict = (
        f"DO UPDATE SET {', '.join(update_pairs)}"
        if update_pairs
        else "DO NOTHING"
    )
    with _connect() as con:
        con.execute(
            f"""INSERT INTO {ANALYSIS_TABLE} ({columns})
                VALUES ({placeholders})
                ON CONFLICT(beatport_id) {on_conflict}""",
            tuple(cols.values()),
        )


# ── DJ sets (any curated tracklist: beatport chart / mixcloud / rekordbox …) ──
#
# Two-level model: dj_sets (header, keyed on name+type) + dj_set_tracks (ordered
# junction on beatport_id). Edits always rewrite the whole junction for a set —
# at ~10-30 tracks that's trivial and sidesteps every position-collision corner
# case (the UNIQUE(set_id, position) index makes incremental shifts fragile).

def _dedup_keep_order(beatport_ids: list[int]) -> list[int]:
    seen: set[int] = set()
    return [b for b in beatport_ids if not (b in seen or seen.add(b))]


def _get_or_create_set_id(con: sqlite3.Connection, name: str, type: str) -> int:
    now = _now()
    con.execute(
        """INSERT INTO dj_sets (name, type, created_at, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(name, type) DO UPDATE SET updated_at = excluded.updated_at""",
        (name, type, now, now),
    )
    return con.execute(
        "SELECT id FROM dj_sets WHERE name = ? AND type = ?", (name, type)
    ).fetchone()[0]


def _set_id(con: sqlite3.Connection, name: str, type: str) -> int:
    row = con.execute(
        "SELECT id FROM dj_sets WHERE name = ? AND type = ?", (name, type)
    ).fetchone()
    if row is None:
        raise KeyError(f"no set named {name!r} of type {type!r}")
    return row[0]


def _rewrite_tracks(con: sqlite3.Connection, set_id: int,
                    ordered_ids: list[int]) -> None:
    """Replace a set's entire ordered track list (positions renumbered 1..N)."""
    now = _now()
    con.execute("DELETE FROM dj_set_tracks WHERE set_id = ?", (set_id,))
    con.executemany(
        """INSERT INTO dj_set_tracks (set_id, beatport_id, position, added_at)
           VALUES (?, ?, ?, ?)""",
        [(set_id, bid, pos, now) for pos, bid in enumerate(ordered_ids, 1)],
    )
    con.execute("UPDATE dj_sets SET updated_at = ? WHERE id = ?", (now, set_id))


def _ordered_ids(con: sqlite3.Connection, set_id: int) -> list[int]:
    return [r[0] for r in con.execute(
        "SELECT beatport_id FROM dj_set_tracks WHERE set_id = ? ORDER BY position",
        (set_id,),
    )]


def record_set(name: str, type: str, beatport_ids: list[int]) -> int:
    """Upsert the (name, type) set and replace its ordered track list.

    `beatport_ids` is stored in order (position 1..N). Re-recording a set fully
    replaces its tracks, so the row always reflects the latest tracklist.
    Returns the set's id. Duplicate ids in the input are dropped (first wins),
    since a track appears at most once per set.
    """
    with _connect() as con:
        set_id = _get_or_create_set_id(con, name, type)
        _rewrite_tracks(con, set_id, _dedup_keep_order(beatport_ids))
    return set_id


def record_built_set(name: str, archetype: str, beatport_ids: list[int],
                     params: dict) -> int:
    """Upsert a set built by build_set.py and persist its build provenance.

    `archetype` is stored as the set's `type` (so the same name can exist per
    archetype, and rebuilding the same name+archetype REPLACES it). `params` is
    JSON-encoded into `dj_sets.params_json` — mood, duration, count, genres, date
    filter and the curve — so the set is self-describing and reproducible.
    Returns the set id.
    """
    import json
    with _connect() as con:
        set_id = _get_or_create_set_id(con, name, archetype)
        con.execute(
            "UPDATE dj_sets SET params_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(params), _now(), set_id),
        )
        _rewrite_tracks(con, set_id, _dedup_keep_order(beatport_ids))
    return set_id


# ----- mutating a stored set in place -------------------------------------

def add_track_to_set(name: str, type: str, beatport_id: int,
                     position: int | None = None) -> None:
    """Insert one track into a set (creating the set if needed).

    `position` is 1-based; None appends to the end. If the track is already in
    the set it is moved to the requested position (or left in place when None).
    """
    with _connect() as con:
        set_id = _get_or_create_set_id(con, name, type)
        ids = [b for b in _ordered_ids(con, set_id) if b != beatport_id]
        idx = len(ids) if position is None else max(0, min(len(ids), position - 1))
        ids.insert(idx, beatport_id)
        _rewrite_tracks(con, set_id, ids)


def remove_track_from_set(name: str, type: str, beatport_id: int) -> bool:
    """Drop a track from a set and close the position gap. False if absent."""
    with _connect() as con:
        set_id = _set_id(con, name, type)
        ids = _ordered_ids(con, set_id)
        if beatport_id not in ids:
            return False
        _rewrite_tracks(con, set_id, [b for b in ids if b != beatport_id])
        return True


def move_track_in_set(name: str, type: str, beatport_id: int,
                      position: int) -> None:
    """Reorder one track to a new 1-based position within its set."""
    with _connect() as con:
        set_id = _set_id(con, name, type)
        ids = _ordered_ids(con, set_id)
        if beatport_id not in ids:
            raise KeyError(f"track {beatport_id} not in set {name!r}")
        ids.remove(beatport_id)
        idx = max(0, min(len(ids), position - 1))
        ids.insert(idx, beatport_id)
        _rewrite_tracks(con, set_id, ids)


def reorder_set(name: str, type: str, beatport_ids: list[int]) -> None:
    """Set the full ordering explicitly. Must be a permutation of current ids."""
    with _connect() as con:
        set_id = _set_id(con, name, type)
        current = set(_ordered_ids(con, set_id))
        new = _dedup_keep_order(beatport_ids)
        if set(new) != current:
            raise ValueError("reorder_set requires the same track set, reordered")
        _rewrite_tracks(con, set_id, new)


def rename_set(name: str, type: str, new_name: str) -> None:
    """Rename a set (its type and tracks are unchanged)."""
    with _connect() as con:
        set_id = _set_id(con, name, type)
        con.execute(
            "UPDATE dj_sets SET name = ?, updated_at = ? WHERE id = ?",
            (new_name, _now(), set_id),
        )


def delete_set(name: str, type: str) -> bool:
    """Delete a set and its tracks (ON DELETE CASCADE). False if it didn't exist."""
    with _connect() as con:
        row = con.execute(
            "SELECT id FROM dj_sets WHERE name = ? AND type = ?", (name, type)
        ).fetchone()
        if row is None:
            return False
        con.execute("DELETE FROM dj_sets WHERE id = ?", (row[0],))
        return True


def list_sets() -> list[sqlite3.Row]:
    """All stored sets with their track counts, newest-updated first."""
    with _connect() as con:
        return con.execute(
            """SELECT s.name, s.type, s.created_at, s.updated_at,
                      COUNT(st.beatport_id) AS track_count
               FROM dj_sets s
               LEFT JOIN dj_set_tracks st ON st.set_id = s.id
               GROUP BY s.id
               ORDER BY s.updated_at DESC""",
        ).fetchall()


def tracks_in_set(name: str, type: str) -> list[sqlite3.Row]:
    """Ordered tracks in a set, joined to enriched metadata where available."""
    with _connect() as con:
        return con.execute(
            """SELECT st.position, st.beatport_id, e.artist, e.title,
                      e.bpm, e.key, e.genre
               FROM dj_set_tracks st
               JOIN dj_sets s ON s.id = st.set_id
               LEFT JOIN enriched_tracks e ON e.beatport_id = st.beatport_id
               WHERE s.name = ? AND s.type = ?
               ORDER BY st.position""",
            (name, type),
        ).fetchall()


def tracks_in_set_id(set_id: int) -> list[sqlite3.Row]:
    """Ordered tracks in a set by its id (the handle build_set.py returns), joined
    to enriched metadata. Used by ad-hoc queries and the export tool."""
    with _connect() as con:
        return con.execute(
            """SELECT st.position, st.beatport_id, e.artist, e.title,
                      e.bpm, e.key, e.genre, e.length_ms
               FROM dj_set_tracks st
               LEFT JOIN enriched_tracks e ON e.beatport_id = st.beatport_id
               WHERE st.set_id = ?
               ORDER BY st.position""",
            (set_id,),
        ).fetchall()


def get_set(set_id: int) -> sqlite3.Row | None:
    """The dj_sets header row (name, type/archetype, params_json, timestamps)."""
    with _connect() as con:
        return con.execute(
            "SELECT id, name, type, created_at, updated_at, params_json "
            "FROM dj_sets WHERE id = ?",
            (set_id,),
        ).fetchone()


def sets_for_track(beatport_id: int) -> list[sqlite3.Row]:
    """Every set a track appears in (name, type, its position there)."""
    with _connect() as con:
        return con.execute(
            """SELECT s.name, s.type, st.position
               FROM dj_set_tracks st
               JOIN dj_sets s ON s.id = st.set_id
               WHERE st.beatport_id = ?
               ORDER BY s.type, s.name""",
            (beatport_id,),
        ).fetchall()


def track_set_count(beatport_id: int) -> int:
    """How many sets a track appears in (one row per set, so a plain count)."""
    with _connect() as con:
        return con.execute(
            "SELECT COUNT(*) FROM dj_set_tracks WHERE beatport_id = ?",
            (beatport_id,),
        ).fetchone()[0]


def used_beatport_ids(exclude_name: str | None = None,
                      exclude_type: str | None = None) -> set[int]:
    """Every beatport_id that appears in ANY stored set — the "already used in a
    past set" exclusion list for build_set's --exclude-used.

    When rebuilding a set in place (same name+archetype REPLACES it), pass that
    set's `exclude_name`+`exclude_type` so its own current tracks don't count as
    "used elsewhere" and block the rebuild.
    """
    with _connect() as con:
        if exclude_name is not None and exclude_type is not None:
            rows = con.execute(
                """SELECT DISTINCT st.beatport_id
                   FROM dj_set_tracks st
                   JOIN dj_sets s ON s.id = st.set_id
                   WHERE NOT (s.name = ? AND s.type = ?)""",
                (exclude_name, exclude_type),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT DISTINCT beatport_id FROM dj_set_tracks"
            ).fetchall()
        return {r[0] for r in rows}
