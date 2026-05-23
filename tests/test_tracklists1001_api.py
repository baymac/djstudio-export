"""Unit tests for detect/tracklists1001_api.py."""

import pytest

from detect.tracklists1001_api import _json_to_paste_text, extract_idtl


def test_extract_idtl():
    assert extract_idtl("https://www.1001tracklists.com/tracklist/abc123/") == "abc123"
    assert extract_idtl("https://www.1001tracklists.com/tracklist/2x7c9km1/") == "2x7c9km1"
    with pytest.raises(ValueError):
        extract_idtl("https://www.1001tracklists.com/dj/somename/")


def test_json_to_paste_text_basic():
    data = [
        {"artistName": "Drumcode", "trackName": "Overdrive", "startTime": "0:30"},
        {"artistName": "Adam Beyer", "trackName": "Your Mind", "startTime": "5:00"},
    ]
    result = _json_to_paste_text(data)
    lines = result.splitlines()
    assert lines[0] == "[0:30] Drumcode - Overdrive"
    assert lines[1] == "[5:00] Adam Beyer - Your Mind"


def test_json_to_paste_text_with_overlay():
    data = [
        {"artistName": "Sasha", "trackName": "Xpander", "startTime": "10:00"},
        {"artistName": "BT", "trackName": "Flaming June", "startTime": "10:00", "isWithTrack": True},
    ]
    result = _json_to_paste_text(data)
    lines = result.splitlines()
    assert lines[0] == "[10:00] Sasha - Xpander"
    assert lines[1] == "w/ BT - Flaming June"


def test_json_to_paste_text_missing_artist_split():
    # When artistName is empty but track contains "Artist - Title", heuristic splits it.
    data = [
        {"artistName": "", "trackName": "Slam - Positive Education", "startTime": "22:15"},
    ]
    result = _json_to_paste_text(data)
    assert result == "[22:15] Slam - Positive Education"


def test_json_to_paste_text_skips_empty():
    data = [
        {"artistName": "", "trackName": "", "startTime": "1:00"},
        {"artistName": "Pan-Pot", "trackName": "Confrontation", "startTime": "30:00"},
    ]
    result = _json_to_paste_text(data)
    lines = result.splitlines()
    assert len(lines) == 1
    assert "Pan-Pot" in lines[0]


def test_json_to_paste_text_no_timestamp():
    data = [{"artistName": "Richie Hawtin", "trackName": "DE9", "startTime": ""}]
    result = _json_to_paste_text(data)
    assert result == "Richie Hawtin - DE9"
