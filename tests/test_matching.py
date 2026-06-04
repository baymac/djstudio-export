"""Unit tests for connections/matching.py — search_query, strip_remix, best_match."""

from connections.matching import best_match, search_query, strip_remix


# ---------------------------------------------------------------------------
# search_query — [] block stripping and () expansion
# ---------------------------------------------------------------------------

def test_search_query_strips_square_bracket_label():
    """Editorial/label tags like [KEINEMUSIK] must be removed entirely."""
    assert search_query("Move (Anyma & Cassian Remix) [KEINEMUSIK]") == "Move Anyma & Cassian Remix"


def test_search_query_strips_square_bracket_tag_only():
    assert search_query("SOS [EXPERTS ONLY]") == "SOS"


def test_search_query_expands_round_brackets_to_words():
    """Remix name in () should survive as searchable words."""
    assert search_query("Song (Ben Böhmer Remix)") == "Song Ben Böhmer Remix"


def test_search_query_strips_feat_bracket_before_label():
    """[feat. X] is stripped, then any trailing [] label is also stripped."""
    assert search_query("Track [feat. Artist] (Club Mix)") == "Track Club Mix"


def test_search_query_multiple_square_brackets():
    assert search_query("Title [Tag1] [Tag2]") == "Title"


def test_search_query_square_bracket_remix_is_expanded():
    """[Ben Böhmer Remix] notation (common on SoundCloud/YouTube) must be kept as words."""
    assert search_query("Song [Ben Böhmer Remix]") == "Song Ben Böhmer Remix"


def test_search_query_square_bracket_mix_is_expanded():
    """[Original Mix] in [] must be expanded, not stripped."""
    assert search_query("Song [Original Mix]") == "Song Original Mix"


def test_search_query_label_stripped_remix_expanded():
    """Both notations in one title: [] label stripped, [] remix expanded."""
    assert search_query("Song [Ben Böhmer Remix] [KEINEMUSIK]") == "Song Ben Böhmer Remix"


def test_search_query_double_bracket_cleaned():
    """Malformed [[nested]] titles must not leave a stray ] in the query."""
    result = search_query("Title [[nested]]")
    assert "]" not in result
    assert "[" not in result


def test_search_query_no_brackets_unchanged():
    assert search_query("Plain Title") == "Plain Title"


# ---------------------------------------------------------------------------
# strip_remix + search_query fallback chain
# ---------------------------------------------------------------------------

def test_strip_remix_followed_by_search_query_clears_label():
    """After stripping (Remix), residual [LABEL] must vanish from the search query."""
    base = strip_remix("Move (Anyma & Cassian Remix) [KEINEMUSIK]")
    assert base == "Move [KEINEMUSIK]"
    assert search_query(base) == "Move"


# ---------------------------------------------------------------------------
# best_match — remix fallback scenarios
# ---------------------------------------------------------------------------

def _track(name, artists, remixers=None):
    return {
        "id": 1,
        "name": name,
        "artists": [{"name": a} for a in artists],
        "remixers": [{"name": r} for r in (remixers or [])],
        "bpm": 128,
        "key": {"camelot_name": "8A"},
        "genre": {"name": "Tech House"},
    }


def test_best_match_finds_remix_in_base_search_results():
    """Scenario: initial search for 'Song Foo Remix' returns nothing useful.
    Fallback searches 'Song' and that result set CONTAINS 'Song (Foo Remix)'.
    best_match(original_title, ...) against base_results should find it.
    """
    original_title = "Song (Foo Remix)"
    artist = "Various"
    base_results = [
        _track("Song (Foo Remix)", ["Various"], remixers=["Foo"]),
        _track("Song (Original Mix)", ["Various"]),
    ]
    match, score = best_match(original_title, artist, base_results)
    assert match is not None
    assert match["name"] == "Song (Foo Remix)"


def test_best_match_falls_back_to_base_title_when_remix_absent():
    """Scenario: specific remix (multi-word remixer) is not on Beatport at all.
    best_match(original_title, ...) scores 0 against the Original Mix because the
    remix tag is non-generic, so we must try best_match(base_title, ...) instead.

    Note: single-word remixers like "(Bar Remix)" are classified generic by
    _GENERIC_REMIX_RE and DO match any version — only multi-word remixers (e.g.
    "Ben Böhmer") are treated as specific and enforce strict remix matching.
    """
    original_title = "Song (Ben Böhmer Remix)"
    base_title = strip_remix(original_title)   # "Song"
    assert base_title == "Song"
    artist = "Monolink"
    # base_results only has the Original Mix — the Ben Böhmer Remix doesn't exist.
    base_results = [_track("Song (Original Mix)", ["Monolink"])]

    remix_match, _ = best_match(original_title, artist, base_results)
    assert remix_match is None, "specific remix must NOT match the wrong mix version"

    base_match, score = best_match(base_title, artist, base_results)
    assert base_match is not None, "base title must match the original mix as fallback"
    assert score >= 0.72
