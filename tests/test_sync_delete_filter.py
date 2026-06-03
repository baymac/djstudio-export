"""sync/cli.py — _filter_targets_to_live drops delete targets already gone from the source app."""
import sync.cli as cli


def test_music_filters_to_live_names(monkeypatch):
    # dj.db is permanent, so "Detected" (deleted earlier) is still a captured target;
    # only playlists currently in Apple Music survive the filter.
    monkeypatch.setattr(cli, "_live_playlist_keys", lambda app: {"Keep Me"})
    targets, labels = cli._filter_targets_to_live("music", ["Keep Me", "Detected"], ["Keep Me", "Detected"])
    assert targets == ["Keep Me"] and labels == ["Keep Me"]


def test_spotify_filters_to_live_ids(monkeypatch):
    monkeypatch.setattr(cli, "_live_playlist_keys", lambda app: {"id_live"})
    targets = [("id_live", "Live"), ("id_gone", "Gone")]
    kept, labels = cli._filter_targets_to_live("spotify", targets, ["Live", "Gone"])
    assert kept == [("id_live", "Live")] and labels == ["Live"]


def test_filter_keeps_all_when_live_unreadable(monkeypatch):
    # Live read failed (None) → keep every target rather than silently skip a real delete.
    monkeypatch.setattr(cli, "_live_playlist_keys", lambda app: None)
    targets, labels = cli._filter_targets_to_live("music", ["A", "B"], ["A", "B"])
    assert targets == ["A", "B"] and labels == ["A", "B"]


def test_filter_keeps_all_when_live_matches_none(monkeypatch):
    # Zero overlap (e.g. wrong Spotify account / empty page) must NOT silently skip
    # every delete — keep all targets so the user can still act. Regression: a stale
    # /me/playlists returned 76 ids that matched none of 76 captured, wrongly yielding
    # "Nothing captured to delete."
    monkeypatch.setattr(cli, "_live_playlist_keys", lambda app: {"other1", "other2"})
    targets = [("p1", "A"), ("p2", "B")]
    kept, labels = cli._filter_targets_to_live("spotify", targets, ["A", "B"])
    assert kept == targets and labels == ["A", "B"]


def test_live_keys_spotify_empty_is_none(monkeypatch):
    from connections import spotify as sp

    class _Client:
        def list_my_playlists(self):
            return []  # empty /me/playlists is suspicious → None (keep all)

        def close(self):
            pass

    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    assert cli._live_playlist_keys("spotify") is None


def test_live_keys_music_empty_is_none(monkeypatch):
    # An empty AppleScript result is treated as "couldn't read" → None (fall back to all).
    from connections import musickit
    monkeypatch.setattr(musickit, "read_live_playlist_names", lambda: set())
    assert cli._live_playlist_keys("music") is None


def test_live_keys_spotify_returns_id_set(monkeypatch):
    from connections import spotify as sp

    class _Client:
        def list_my_playlists(self):
            return [{"id": "a"}, {"id": "b"}]

        def close(self):
            pass

    monkeypatch.setattr(sp, "make_client", lambda: _Client())
    assert cli._live_playlist_keys("spotify") == {"a", "b"}


def test_live_keys_spotify_auth_error_is_none(monkeypatch):
    from connections import spotify as sp
    def boom():
        raise sp.SpotifyAuthError("no creds")
    monkeypatch.setattr(sp, "make_client", boom)
    assert cli._live_playlist_keys("spotify") is None
