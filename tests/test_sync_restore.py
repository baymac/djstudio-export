"""sync/restore.py — bulk Apple Music restore orchestration (musickit + db mocked)."""
from types import SimpleNamespace

import sync.restore as restore
from sync.cli import _restore_scopes


def _ns(**kw):
    base = dict(restore_all=False, restore_library=False, restore_playlists=False,
                restore_favorites=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_restore_scopes_all_expands():
    assert _restore_scopes(_ns(restore_all=True)) == {"library", "playlists", "favorites"}


def test_restore_scopes_combine_library_and_favorites():
    assert _restore_scopes(_ns(restore_library=True, restore_favorites=True)) == {"library", "favorites"}


def test_restore_scopes_none():
    assert _restore_scopes(_ns()) == set()


def _row(title, cid="c", pid="p"):
    return {"title": title, "artist": "A", "album": "", "native_track_id": cid,
            "native_persistent_id": pid}


def test_library_readd_skips_present_and_skips_missing_catalog_id(monkeypatch):
    rows = [_row("InLib", cid="1"), _row("Missing", cid="2"), _row("NoCid", cid="")]
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist",
                        lambda app, pid, **k: [dict(r) for r in rows])
    # "InLib" already in the library → dropped by --readd-missing; "NoCid" has no
    # catalog id → not re-addable.
    monkeypatch.setattr(restore.musickit, "read_library_track_keys",
                        lambda: {restore.musickit.library_track_key("InLib", "A")})
    added = []
    monkeypatch.setattr(restore.musickit, "readd_track_by_catalog_id", lambda cid: added.append(cid))
    monkeypatch.setattr(restore.time, "sleep", lambda s: None)

    restore.restore_music(scopes={"library"}, readd_missing=True, dry_run=False, verbose=False)
    assert added == ["2"]  # only the missing track with a catalog id


def test_dry_run_library_adds_nothing(monkeypatch):
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist",
                        lambda app, pid, **k: [_row("X", cid="1")])
    hit = []
    monkeypatch.setattr(restore.musickit, "readd_track_by_catalog_id", lambda cid: hit.append(cid))
    restore.restore_music(scopes={"library"}, readd_missing=False, dry_run=True, verbose=False)
    assert hit == []  # dry-run never mutates


def test_favorites_marks_loved(monkeypatch):
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist",
                        lambda app, pid, **k: [_row("Fav", cid="9")])
    loved = {}
    monkeypatch.setattr(restore.musickit, "mark_loved",
                        lambda tracks: loved.setdefault("n", len(tracks)) or len(tracks))
    restore.restore_music(scopes={"favorites"}, readd_missing=False, dry_run=False, verbose=False)
    assert loved["n"] == 1


def test_music_playlists_recreated_per_playlist(monkeypatch):
    # __library__/__favorites__ are excluded; each user playlist is recreated via
    # create_apple_playlist with its captured rows.
    monkeypatch.setattr(restore.sync_db, "list_playlists", lambda app, **k: [
        {"native_playlist_id": "pl1", "playlist_name": "Ibiza"},
        {"native_playlist_id": "__library__", "playlist_name": "Library"},
        {"native_playlist_id": "__favorites__", "playlist_name": "Favourite Songs"},
    ])
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist",
                        lambda app, pid, **k: [_row("T", cid="1")])
    made = []
    monkeypatch.setattr(restore.musickit, "create_apple_playlist",
                        lambda name, rows: made.append((name, len(rows)))
                        or {"requested": len(rows), "added": len(rows)})
    restore.restore_music(scopes={"playlists"}, readd_missing=False, dry_run=False, verbose=False)
    assert made == [("Ibiza", 1)]  # only the user playlist, not the pseudo-collections


def test_spotify_live_recreates_playlists_and_saves_library(monkeypatch):
    import connections.spotify as sp
    monkeypatch.setattr(restore.sync_db, "list_playlists", lambda app, **k: [
        {"native_playlist_id": "p1", "playlist_name": "Mix"},
        {"native_playlist_id": "__library__", "playlist_name": "Liked"},
    ])
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist",
                        lambda app, pid, **k: [_row("T", cid=f"{pid}-trk")])
    created, added, saved = [], [], []

    class _Client:
        def current_user_id(self):
            return "u1"

        def create_playlist(self, user_id, name):
            created.append((user_id, name))
            return "newpid"

        def add_tracks(self, pid, ids):
            added.append((pid, ids))
            return len(ids)

        def save_tracks(self, ids):
            saved.append(ids)
            return len(ids)

        def close(self):
            pass

    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    restore.restore_spotify(scopes={"library", "playlists"}, dry_run=False, verbose=False)
    # __library__ excluded from the playlist loop; recreated by id, then Liked re-saved.
    assert created == [("u1", "Mix")]
    assert added == [("newpid", ["p1-trk"])]
    assert saved == [["__library__-trk"]]


def test_spotify_dry_run_makes_no_client(monkeypatch):
    # dry-run must not even construct a Spotify client.
    import connections.spotify as sp
    monkeypatch.setattr(restore.sync_db, "list_playlists", lambda app, **k: [])
    monkeypatch.setattr(restore.sync_db, "tracks_in_native_playlist", lambda app, pid, **k: [])

    def boom():
        raise AssertionError("should not build a client in dry-run")
    monkeypatch.setattr(sp, "make_client", boom)
    restore.restore_spotify(scopes={"library", "playlists"}, dry_run=True, verbose=False)


def test_beatport_recreates_each_playlist(monkeypatch):
    from detect import db as detect_db
    monkeypatch.setattr(detect_db, "list_beatport_playlists",
                        lambda: [{"beatport_id": 1, "name": "Afro", "track_count": 2}])
    monkeypatch.setattr(detect_db, "beatport_track_ids_in_playlist", lambda bid: [11, 22])

    created, added = [], []

    class _BP:
        def create_playlist(self, name):
            created.append(name)
            return {"id": 999}

        def add_track(self, dest, tid):
            added.append((dest, tid))

    import connections.beatport as bpmod
    monkeypatch.setattr(bpmod, "make_bp_client", lambda: (_BP(), type("C", (), {"close": lambda s: None})()))
    restore.restore_beatport(dry_run=False, verbose=False)
    assert created == ["Afro"]
    assert added == [(999, 11), (999, 22)]
