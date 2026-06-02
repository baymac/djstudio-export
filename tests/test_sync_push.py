"""sync/push.py — selection + per-app orchestration (external clients mocked)."""
import pytest

import sync.db as sdb
from sync import push


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "dj_test.db"
    monkeypatch.setattr(sdb, "DB_PATH", path)
    sdb.init_db(path)
    return path


def _seed():
    a = sdb.insert_sync_track("apple_music", native_track_id="cat1", artist="A", title="T1")
    b = sdb.insert_sync_track("apple_music", native_track_id="cat2", artist="B", title="T2")
    s = sdb.insert_sync_track("spotify", native_track_id="sp1", artist="C", title="T3")
    return a, b, s


def test_push_apple_by_ids(monkeypatch):
    a, b, s = _seed()
    captured = {}

    def fake_create(name, tracks):
        captured["name"] = name
        captured["tracks"] = tracks
        return {"created": True, "name": name, "added": len(tracks), "requested": len(tracks)}

    monkeypatch.setattr("connections.musickit.create_apple_playlist", fake_create)
    # include the spotify id too — it must be filtered out (wrong app).
    push.push_playlist("music", "Set A", ids=[a, b, s], dry_run=False)
    assert captured["name"] == "Set A"
    assert [(t["artist"], t["title"]) for t in captured["tracks"]] == [("A", "T1"), ("B", "T2")]


def test_push_apple_dry_run_does_not_call_bridge(monkeypatch):
    a, b, _ = _seed()
    called = {"n": 0}
    monkeypatch.setattr("connections.musickit.create_apple_playlist",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    push.push_playlist("music", "Set A", ids=[a, b], dry_run=True)
    assert called["n"] == 0


def test_push_spotify_creates_and_adds(monkeypatch):
    _, _, s = _seed()
    events = []

    class _FakeSpotify:
        def current_user_id(self):
            return "user1"

        def create_playlist(self, user_id, name):
            events.append(("create", user_id, name))
            return "pl_new"

        def add_tracks(self, playlist_id, track_ids):
            events.append(("add", playlist_id, list(track_ids)))
            return len(track_ids)

        def close(self):
            events.append(("close",))

    monkeypatch.setattr("connections.spotify.make_client", lambda: _FakeSpotify())
    push.push_playlist("spotify", "Spot Set", ids=[s], dry_run=False)
    assert ("create", "user1", "Spot Set") in events
    assert ("add", "pl_new", ["sp1"]) in events
    assert ("close",) in events


def test_push_query_selection(monkeypatch):
    _seed()
    captured = {}
    monkeypatch.setattr("connections.musickit.create_apple_playlist",
                        lambda name, tracks: captured.update(name=name, tracks=tracks) or {"added": len(tracks)})
    push.push_playlist(
        "music", "Q",
        query="SELECT * FROM sync_tracks WHERE title = 'T1'",
        dry_run=False,
    )
    assert [t["title"] for t in captured["tracks"]] == ["T1"]


def test_push_query_missing_columns_errors(monkeypatch):
    _seed()
    with pytest.raises(SystemExit):
        push.push_playlist("music", "Q", query="SELECT title FROM sync_tracks", dry_run=False)


def test_applescript_builder_escapes_quotes():
    from connections.musickit import build_create_playlist_applescript
    script = build_create_playlist_applescript(
        'My "Best" Set', [{"artist": 'A "x"', "title": "T1"}]
    )
    assert 'make new user playlist with properties {name:"My \\"Best\\" Set"}' in script
    assert 'whose name is "T1" and artist is "A \\"x\\""' in script
    assert script.strip().endswith("end tell")
    assert "duplicate chosen to newPl" in script


def test_push_no_selection_errors():
    _seed()
    with pytest.raises(SystemExit):
        push.push_playlist("music", "Q", dry_run=False)


def test_push_empty_result_is_noop(monkeypatch):
    _seed()
    called = {"n": 0}
    monkeypatch.setattr("connections.musickit.create_apple_playlist",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    # ids that don't exist → no rows → no bridge call, no crash
    push.push_playlist("music", "Q", ids=[9999], dry_run=False)
    assert called["n"] == 0
