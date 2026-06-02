"""connections/spotify.py — pure helpers + API methods with a faked httpx client."""
import connections.spotify as sp


def test_track_uri_normalises_bare_id():
    assert sp._track_uri("abc123") == "spotify:track:abc123"


def test_track_uri_passes_through_uri():
    assert sp._track_uri("spotify:track:xyz") == "spotify:track:xyz"


def test_entries_from_items_maps_and_skips_local():
    client = sp.Spotify("dummy")
    items = [
        {"track": {"id": "1", "name": "Glue",
                   "artists": [{"name": "Bicep"}],
                   "album": {"name": "Bicep"},
                   "external_urls": {"spotify": "https://open.spotify.com/track/1"}}},
        {"track": {"id": None, "name": "Local"}},          # local file → skipped
        {"track": {"id": "2", "name": "", "artists": []}},  # no artist/title → skipped
    ]
    rows = client._entries_from_items(items)
    client.close()
    assert len(rows) == 1
    assert rows[0]["native_track_id"] == "1"
    assert rows[0]["artist"] == "Bicep"
    assert rows[0]["title"] == "Glue"
    assert rows[0]["native_url"].endswith("/track/1")


def test_entries_from_items_skips_null_artist_name():
    """An artist with a null `name` (local files, podcast episodes) must not crash
    the join — the track is skipped, valid tracks still captured."""
    client = sp.Spotify("dummy")
    items = [
        {"track": {"id": "3", "name": "Some Episode",
                   "artists": [{"name": None}]}},            # null name → skipped, no crash
        {"track": {"id": "4", "name": "Track",
                   "artists": [{"name": None}, {"name": "Real Artist"}]}},  # partial → kept
        {"track": {"id": "5", "name": "Keeper",
                   "artists": [{"name": "Solo"}]}},
    ]
    rows = client._entries_from_items(items)
    client.close()
    assert [r["native_track_id"] for r in rows] == ["4", "5"]
    assert rows[0]["artist"] == "Real Artist"
    assert rows[1]["artist"] == "Solo"


class _FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 300:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_add_tracks_batches_in_hundreds(monkeypatch):
    client = sp.Spotify("dummy")
    calls = []

    def fake_post(url, json=None, **kw):
        calls.append(json["uris"])
        return _FakeResp(200)

    monkeypatch.setattr(client.client, "post", fake_post)
    ids = [str(i) for i in range(250)]
    added = client.add_tracks("pl1", ids)
    client.close()
    assert added == 250
    assert [len(c) for c in calls] == [100, 100, 50]
    assert calls[0][0] == "spotify:track:0"  # bare ids normalised to uris


def test_create_playlist_returns_id(monkeypatch):
    client = sp.Spotify("dummy")

    class _R(_FakeResp):
        def json(self):
            return {"id": "newpl"}

    monkeypatch.setattr(client.client, "post", lambda url, json=None, **kw: _R(200))
    pid = client.create_playlist("user1", "My Set")
    client.close()
    assert pid == "newpl"


def test_unfollow_playlist_hits_followers_endpoint(monkeypatch):
    client = sp.Spotify("dummy")
    calls = []

    def fake_delete(url, **kw):
        calls.append(url)
        return _FakeResp(200)

    monkeypatch.setattr(client.client, "delete", fake_delete)
    client.unfollow_playlist("pl42")
    client.close()
    assert calls == [f"{sp._API}/playlists/pl42/followers"]


def test_clear_saved_tracks_batches_by_fifty(monkeypatch):
    client = sp.Spotify("dummy")
    # 120 liked tracks → 50 + 50 + 20 DELETE batches.
    monkeypatch.setattr(client, "saved_tracks",
                        lambda: [{"native_track_id": str(i)} for i in range(120)])
    batches = []

    def fake_request(method, url, json=None, **kw):
        assert method == "DELETE"
        assert url == f"{sp._API}/me/tracks"
        batches.append(json["ids"])
        return _FakeResp(200)

    monkeypatch.setattr(client.client, "request", fake_request)
    removed = client.clear_saved_tracks()
    client.close()
    assert removed == 120
    assert [len(b) for b in batches] == [50, 50, 20]


def test_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    try:
        sp._credentials()
        assert False, "expected SpotifyAuthError"
    except sp.SpotifyAuthError:
        pass
