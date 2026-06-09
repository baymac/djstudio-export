"""sync/capture.py — capture-scope selection (the _capture_* helpers are stubbed)."""
import sync.capture as cap


def _stub_music(monkeypatch):
    calls = []
    monkeypatch.setattr(cap, "_capture_all_playlists", lambda *a, **k: calls.append("playlists"))
    monkeypatch.setattr(cap, "_capture_library", lambda *a, **k: calls.append("library"))
    monkeypatch.setattr(cap, "_capture_favorites", lambda *a, **k: calls.append("favorites"))
    return calls


def test_music_default_scope_is_all(monkeypatch):
    # Default scope "all" → playlists + the whole library collection (favs + library).
    calls = _stub_music(monkeypatch)
    cap.run_sync_music()
    assert calls == ["playlists", "favorites", "library"]


def test_music_all_scope(monkeypatch):
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(scope="all")
    assert calls == ["playlists", "favorites", "library"]


def test_music_playlists_scope_excludes_library(monkeypatch):
    # --playlists must NOT pull in library/favorites.
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(scope="playlists")
    assert calls == ["playlists"]


def test_music_library_scope_is_favorites_plus_library(monkeypatch):
    # --library means the whole personal collection: Favourite Songs + library songs.
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(scope="library")
    assert calls == ["favorites", "library"]


def test_music_named_playlist_captures_playlists_only(monkeypatch):
    # A named --playlist narrows to playlists regardless of scope.
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(playlist="Ibiza")
    assert calls == ["playlists"]


def test_favorites_collapses_duplicates(monkeypatch):
    # Apple's Favourite Songs stream can return the same track twice; favorites is a
    # loved-SET, so capture must dedupe before persisting (by catalog id, else artist+title).
    stream = [
        {"catalog_id": "1", "artist": "A", "name": "x", "album": "al"},
        {"catalog_id": "2", "artist": "B", "name": "y", "album": "al"},
        {"catalog_id": "1", "artist": "A", "name": "x", "album": "al"},   # dup by id
        {"catalog_id": None, "artist": "C", "name": "z", "album": "al"},
        {"catalog_id": None, "artist": " c ", "name": "Z", "album": "al"},  # dup by artist+title
        # Pipe in title/artist must NOT false-collide: ("a|b","c") vs ("a","b|c")
        # would collapse under a naive "artist|title" key but are distinct tracks.
        {"catalog_id": None, "artist": "a|b", "name": "c", "album": "al"},
        {"catalog_id": None, "artist": "a", "name": "b|c", "album": "al"},
    ]
    monkeypatch.setattr(cap.musickit, "stream_favorite_tracks", lambda: iter(stream))
    persisted = {}
    monkeypatch.setattr(cap.sync_db, "replace_playlist",
                        lambda app, npid, rows, **k: persisted.update(rows=rows)
                        or {"new": len(rows), "kept": 0, "removed": 0, "total": len(rows)})

    cap._capture_favorites(limit=0, verbose=False, dry_run=False)

    rows = persisted["rows"]
    assert [r["native_track_id"] for r in rows] == ["1", "2", None, None, None]
    assert [r["position"] for r in rows] == [0, 1, 2, 3, 4]  # positions re-numbered after collapse
    assert [(r["artist"], r["title"]) for r in rows[2:]] == [
        ("C", "z"), ("a|b", "c"), ("a", "b|c")]  # pipe tracks kept distinct


def test_spotify_default_targets_playlists_and_liked(monkeypatch):
    captured = []

    class _Client:
        def list_my_playlists(self):
            return [{"id": "p1", "name": "Mix"}]

        def playlist_tracks(self, pid):
            return []

        def saved_tracks(self):
            return []

        def close(self):
            pass

    import connections.spotify as sp
    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    monkeypatch.setattr(cap.sync_db, "replace_playlist",
                        lambda app, npid, rows, **k: captured.append(npid)
                        or {"new": 0, "kept": 0, "removed": 0, "total": 0})
    # Default scope "all" captures both playlists and Liked Songs.
    cap._run_sync_spotify_impl(scope="all", playlist=None, limit=0, verbose=False, dry_run=False)
    assert "p1" in captured and cap.LIBRARY_PID in captured


def test_spotify_playlists_scope_excludes_liked(monkeypatch):
    captured = []

    class _Client:
        def list_my_playlists(self):
            return [{"id": "p1", "name": "Mix"}]

        def playlist_tracks(self, pid):
            return []

        def saved_tracks(self):
            raise AssertionError("Liked Songs must not be fetched for --playlists")

        def close(self):
            pass

    import connections.spotify as sp
    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    monkeypatch.setattr(cap.sync_db, "replace_playlist",
                        lambda app, npid, rows, **k: captured.append(npid)
                        or {"new": 0, "kept": 0, "removed": 0, "total": 0})
    cap._run_sync_spotify_impl(scope="playlists", playlist=None, limit=0, verbose=False, dry_run=False)
    assert captured == ["p1"] and cap.LIBRARY_PID not in captured


def test_spotify_library_scope_is_liked_only(monkeypatch):
    captured = []

    class _Client:
        def list_my_playlists(self):
            raise AssertionError("playlists must not be listed for --library")

        def saved_tracks(self):
            return []

        def close(self):
            pass

    import connections.spotify as sp
    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    monkeypatch.setattr(cap.sync_db, "replace_playlist",
                        lambda app, npid, rows, **k: captured.append(npid)
                        or {"new": 0, "kept": 0, "removed": 0, "total": 0})
    cap._run_sync_spotify_impl(scope="library", playlist=None, limit=0, verbose=False, dry_run=False)
    assert captured == [cap.LIBRARY_PID]
