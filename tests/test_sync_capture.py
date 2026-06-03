"""sync/capture.py — capture-scope selection (the _capture_* helpers are stubbed)."""
import sync.capture as cap


def _stub_music(monkeypatch):
    calls = []
    monkeypatch.setattr(cap, "_capture_all_playlists", lambda *a, **k: calls.append("playlists"))
    monkeypatch.setattr(cap, "_capture_library", lambda *a, **k: calls.append("library"))
    monkeypatch.setattr(cap, "_capture_favorites", lambda *a, **k: calls.append("favorites"))
    return calls


def test_music_default_captures_everything(monkeypatch):
    # No scope flag → capture all three collections.
    calls = _stub_music(monkeypatch)
    cap.run_sync_music()
    assert calls == ["playlists", "library", "favorites"]


def test_music_named_playlist_captures_playlists_only(monkeypatch):
    # A named --playlist narrows to playlists (not the whole library).
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(playlist="Ibiza")
    assert calls == ["playlists"]


def test_music_library_only(monkeypatch):
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(use_library=True)
    assert calls == ["library"]


def test_music_library_and_favorites_combine(monkeypatch):
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(use_library=True, use_favorites=True)
    assert calls == ["library", "favorites"]  # no playlists


def test_music_all_captures_everything(monkeypatch):
    calls = _stub_music(monkeypatch)
    cap.run_sync_music(use_all=True)
    assert calls == ["playlists", "library", "favorites"]


def test_spotify_all_targets_playlists_and_liked(monkeypatch):
    # Stub the client + replace_playlist so we can read which targets were captured.
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
    # Default (no scope) captures both, same as explicit --all.
    cap._run_sync_spotify_impl(playlist=None, use_library=False, use_all=False,
                               limit=0, verbose=False, dry_run=False)
    assert "p1" in captured and cap.LIBRARY_PID in captured
