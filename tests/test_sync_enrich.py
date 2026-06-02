"""sync enrich (shared engine + sync adapter) and the make_bp_client consolidation."""
import contextlib

import pytest

import detect.db as ddb
import sync.db as sdb


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "dj_test.db"
    # Both modules must point at the same dj.db: capture writes sync_tracks,
    # enrich writes enriched_tracks.
    monkeypatch.setattr(ddb, "DB_PATH", path)
    monkeypatch.setattr(sdb, "DB_PATH", path)
    ddb.migrate()
    sdb.init_db(path)
    return path


def _match(bid, slug, name, artist, bpm, camelot, genre):
    return {
        "id": bid, "slug": slug, "name": name,
        "artists": [{"name": artist}],
        "bpm": bpm, "key": {"camelot_name": camelot},
        "genre": {"name": genre},
    }


class _FakeBeatport:
    def search_tracks(self, query, per_page=10, debug=False):
        q = query.lower()
        if "glue" in q:
            return [_match(9001, "glue", "Glue", "Bicep", 126, "8A", "Tech House")]
        if "baby" in q:
            return [_match(9002, "baby", "Baby", "Four Tet", 120, "5A", "House")]
        return []

    def get_track(self, track_id):
        return {}


class _FakeClient:
    def close(self):
        pass


@pytest.fixture
def fake_beatport(monkeypatch):
    import enrich.engine as enrich
    monkeypatch.setattr(enrich.bp_api, "make_bp_client", lambda **kw: (_FakeBeatport(), _FakeClient()))
    # Don't spawn the real `caffeinate` subprocess in tests.
    monkeypatch.setattr(enrich, "caffeinate", contextlib.nullcontext)


def test_sync_enrich_writes_deduped_enriched(tmp_db, fake_beatport):
    from sync.enrich_adapter import run_sync_enrich

    # Glue appears TWICE (faithful capture allows dups) + Baby once.
    sdb.replace_playlist("apple_music", "pid1", [
        {"native_track_id": "g1", "artist": "Bicep", "title": "Glue", "playlist_name": "P", "position": 0},
        {"native_track_id": "g2", "artist": "Bicep", "title": "Glue", "playlist_name": "P", "position": 1},
        {"native_track_id": "b1", "artist": "Four Tet", "title": "Baby", "playlist_name": "P", "position": 2},
    ])

    run_sync_enrich(dry_run=False, limit=0, verbose=False, threshold=0.1, retry_misses=False)

    # enriched_tracks dedups by beatport_id: Glue once, Baby once.
    rows = ddb.list_enriched_tracks(limit=50)
    bp_ids = sorted(r["beatport_id"] for r in rows)
    assert bp_ids == [9001, 9002]

    # All sync rows resolved; the duplicate Glue links to the same beatport_id.
    import sqlite3
    con = sqlite3.connect(tmp_db)
    state = con.execute(
        "SELECT title, enrich_outcome, enriched_beatport_id FROM sync_tracks ORDER BY id"
    ).fetchall()
    con.close()
    glue_outcomes = [s[1] for s in state if s[0] == "Glue"]
    assert "found" in glue_outcomes and "duplicate" in glue_outcomes
    assert all(s[2] == 9001 for s in state if s[0] == "Glue")
    baby = [s for s in state if s[0] == "Baby"][0]
    assert baby[1] == "found" and baby[2] == 9002


def test_sync_enrich_marks_not_found(tmp_db, fake_beatport):
    from sync.enrich_adapter import run_sync_enrich
    rid = sdb.insert_sync_track("apple_music", artist="Nobody", title="Untraceable Tune")
    run_sync_enrich(dry_run=False, limit=0, verbose=False, threshold=0.1, retry_misses=False)
    assert sdb.get_sync_track(rid)["enrich_outcome"] == "not_found"


def test_make_bp_client_moved_to_connections(monkeypatch):
    """REGRESSION: make_bp_client now lives in connections.beatport; importers must work."""
    import connections.beatport as bp
    monkeypatch.setattr(bp, "resolve_access_token", lambda **kw: "Bearer testtoken")
    beatport, client = bp.make_bp_client()
    try:
        assert beatport.client.headers["authorization"] == "Bearer testtoken"
        assert callable(beatport.on_401)
    finally:
        client.close()


def test_export_and_helpers_import_make_bp_client():
    """REGRESSION: the two repointed callers import cleanly from the new home."""
    import importlib
    to_beatport = importlib.import_module("export.to_beatport")
    helper = importlib.import_module("helpers.delete_beatport_track")
    from connections.beatport import make_bp_client
    assert make_bp_client is not None
    assert hasattr(to_beatport, "push_to_beatport")
    assert hasattr(helper, "main")
