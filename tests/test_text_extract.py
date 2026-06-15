"""Unit tests for detect/text.py tracklist parsing."""

from detect.text import extract_from_text


def test_skips_session_header_line():
    # 1001tracklists prepends "DJ - Show Name YYYY-MM-DD" as a pseudo-track.
    # It has a ' - ' separator but no timestamp and ends in a bare ISO date,
    # so it must be dropped (not counted as a track, not reported as skipped).
    raw = (
        "ACRAZE - Paradox Radio 060 2026-06-03\n"
        "[0:30] Wheats - What I Might Do\n"
        "[3:10] JOSHWA - Out Of My Mind (Rello Remix)\n"
    )
    tracks, skipped = extract_from_text(raw)
    assert [t["title"] for t in tracks] == [
        "What I Might Do",
        "Out Of My Mind (Rello Remix)",
    ]
    assert all("Paradox Radio" not in t["title"] for t in tracks)
    assert tracks[0]["position"] == 1  # numbering starts at the first real track
    assert skipped == []


def test_timestamped_track_ending_in_date_is_kept():
    # A real track with a timestamp is never treated as a header even if its
    # title happens to end in something date-like.
    raw = "[1:00] Some Artist - Live Set 2026-01-01\n"
    tracks, _ = extract_from_text(raw)
    assert len(tracks) == 1
    assert tracks[0]["title"] == "Live Set 2026-01-01"


def test_plain_list_without_timestamps_unaffected():
    raw = "Daft Punk - Around The World\nJustice - Genesis\n"
    tracks, skipped = extract_from_text(raw)
    assert [(t["artist"], t["title"]) for t in tracks] == [
        ("Daft Punk", "Around The World"),
        ("Justice", "Genesis"),
    ]
    assert skipped == []


def test_plain_list_track_ending_in_date_is_kept():
    # A plain-list tracklist (no timestamps) must NOT drop tracks whose title
    # ends in an ISO date — the header guard fires only for timed tracklists.
    raw = (
        "Bicep - Glue 2017-06-02\n"
        "Fisher - Losing It 2018-09-21\n"
    )
    tracks, skipped = extract_from_text(raw)
    assert [(t["artist"], t["title"]) for t in tracks] == [
        ("Bicep", "Glue 2017-06-02"),
        ("Fisher", "Losing It 2018-09-21"),
    ]
    assert skipped == []


def test_id_placeholder_lines_skipped():
    # "ID – ID" and "Artist – ID" are unidentified-track placeholders; neither
    # should enter the track list. They land in skipped (not silently dropped)
    # so the caller can surface them to the user.
    raw = (
        "[0:00] Max Styler & Pavel Petrov - ID\n"
        "[3:00] ID - ID\n"
        "[6:00] Fisher - Losing It\n"
    )
    tracks, skipped = extract_from_text(raw)
    assert [(t["artist"], t["title"]) for t in tracks] == [("Fisher", "Losing It")]
    assert any("Max Styler" in s for s in skipped)
    assert any("ID - ID" in s for s in skipped)


def test_overlay_line_matching_header_pattern_is_kept():
    # A "w/" overlay line that happens to end in an ISO date must NOT be
    # treated as a header — the is_overlay guard short-circuits the check.
    # Overlay lines become their own tracks, inheriting the parent timestamp.
    raw = (
        "[0:30] Wheats - What I Might Do\n"
        "w/ ACRAZE - Paradox Radio 060 2026-06-03\n"
    )
    tracks, skipped = extract_from_text(raw)
    # Both the parent and the overlay survive (overlay inherits parent timestamp).
    assert len(tracks) == 2
    assert tracks[0]["title"] == "What I Might Do"
    assert tracks[1]["artist"] == "ACRAZE"
    assert tracks[1]["timestamp_s"] == 30  # inherited from parent
    assert skipped == []
