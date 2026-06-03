"""connections/musickit.py — pure AppleScript builders (no Music.app needed)."""
import connections.musickit as mk


def test_delete_applescript_targets_playlist_by_name():
    script = mk.build_delete_playlist_applescript("Summer Mix")
    # Matches by name across all playlists, but only deletable ones (special kind
    # none) — so subscription playlists ("<artist> Essentials") are included while
    # the system playlists (Library/Music/Purchased) are excluded.
    assert 'every playlist whose name is "Summer Mix" and special kind is none' in script
    assert "delete p" in script
    # Deletes the container only — returns how many playlists matched.
    assert "return n as string" in script
    # `matched` is a reserved Music.app term (smart-playlist match rule); using it as
    # a variable raises -10003 "Access not allowed". Guard against a regression.
    assert "set matched to" not in script


def test_delete_applescript_escapes_quotes():
    script = mk.build_delete_playlist_applescript('My "Best" Set')
    assert '\\"Best\\"' in script


def test_create_playlist_uses_album_tiebreaker_when_known():
    script = mk.build_create_playlist_applescript("Set", [
        {"title": "Glue", "artist": "Bicep", "album": "Bicep"},
    ])
    # name+artist filter, plus an album tiebreaker that never drops item 1.
    assert 'whose name is "Glue" and artist is "Bicep"' in script
    assert "set chosen to item 1 of ms" in script
    assert '(album of c) is "Bicep"' in script


def test_create_playlist_no_album_block_without_album():
    script = mk.build_create_playlist_applescript("Set", [
        {"title": "Opal", "artist": "Bicep"},  # no album → no tiebreaker loop
    ])
    assert "album of" not in script
    assert "set chosen to item 1 of ms" in script


def test_create_playlist_prefers_persistent_id_then_falls_back():
    script = mk.build_create_playlist_applescript("Set", [
        {"title": "Glue", "artist": "Bicep", "native_persistent_id": "41EA5F8B718954FE"},
    ])
    # Exact persistent-id match first, name+artist as fallback (chosen still missing).
    assert 'whose persistent ID is "41EA5F8B718954FE"' in script
    assert "if chosen is missing value then" in script
    assert 'whose name is "Glue" and artist is "Bicep"' in script


def test_create_playlist_no_persistent_block_without_id():
    script = mk.build_create_playlist_applescript("Set", [{"title": "Opal", "artist": "Bicep"}])
    assert "persistent ID is" not in script


def test_read_persistent_ids_parses_tab_lines(monkeypatch):
    monkeypatch.setattr(mk, "_run_osascript",
                        lambda *a, **k: "AAA\tMissing U\nBBB\tDopamine\n")
    assert mk.read_playlist_persistent_ids("Old anthems") == [("AAA", "Missing U"), ("BBB", "Dopamine")]


def test_read_persistent_ids_ambiguous_returns_none(monkeypatch):
    monkeypatch.setattr(mk, "_run_osascript", lambda *a, **k: "AMBIGUOUS")
    assert mk.read_playlist_persistent_ids("Chill") is None


def test_read_persistent_ids_swallows_applescript_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("osascript failed")
    monkeypatch.setattr(mk, "_run_osascript", boom)
    assert mk.read_playlist_persistent_ids("Gone") is None


def test_library_track_key_normalises():
    assert mk.library_track_key("  Glue ", "Bicep") == mk.library_track_key("glue", "BICEP")
    assert mk.library_track_key("A", "B") != mk.library_track_key("A", "C")


def test_mark_loved_applescript_prefers_persistent_id():
    script = mk.build_mark_loved_applescript([
        {"title": "Glue", "artist": "Bicep", "native_persistent_id": "PID9"},
    ])
    assert 'whose persistent ID is "PID9"' in script
    assert "set loved of chosen to true" in script
    assert 'whose name is "Glue" and artist is "Bicep"' in script  # fallback present


def test_live_playlist_names_parses_lines(monkeypatch):
    monkeypatch.setattr(mk, "_run_osascript", lambda *a, **k: "Detected\nOld anthems\n\n")
    assert mk.read_live_playlist_names() == {"Detected", "Old anthems"}


def test_live_playlist_names_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("osascript failed")
    monkeypatch.setattr(mk, "_run_osascript", boom)
    # Error → empty set so the caller falls back to attempting every captured target.
    assert mk.read_live_playlist_names() == set()


def test_readd_track_noop_on_empty(monkeypatch):
    called = []
    monkeypatch.setattr(mk, "_run_osascript", lambda *a, **k: called.append(a))
    mk.readd_track_by_catalog_id("")
    assert called == []  # no catalog id → no osascript


def test_readd_track_opens_itmss_url(monkeypatch):
    seen = {}
    monkeypatch.setattr(mk, "_run_osascript", lambda script, **k: seen.setdefault("s", script))
    mk.readd_track_by_catalog_id("1440857781")
    assert "itmss://itunes.apple.com/song?id=1440857781" in seen["s"]
