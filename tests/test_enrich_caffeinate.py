"""Tests that the enrich engine uses caffeinate when tracks exist, not when there are none."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

import enrich.engine as enrich_mod


@pytest.fixture
def mock_caffeinate():
    entered = []

    @contextmanager
    def _fake():
        entered.append(True)
        yield
        entered.append(False)

    with patch("enrich.engine.caffeinate", _fake):
        yield entered


@pytest.fixture
def mock_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich_mod, "_LOG_DIR", tmp_path)


class _FakeAdapter:
    """Minimal SourceAdapter that lets run_enrich_engine run without any I/O.

    `load_candidates` decides whether the engine reaches the caffeinated loop;
    every other method is a no-op so a candidate track flows through to a clean
    not_found (the Beatport client is mocked to return no search results).
    """

    name = "Enrich"

    def __init__(self, tracks):
        self._tracks = tracks

    def load_candidates(self, retry_misses):
        return self._tracks

    def secret_count(self):
        return 0

    def seen_pairs(self):
        return []

    def start_run(self):
        return 1

    def finish_run(self, *a, **k):
        pass

    def mark_secret(self, row_id):
        pass

    def mark_miss(self, row_id, outcome):
        pass

    def link_existing(self, row_id, beatport_id):
        return False

    def save_enriched(self, row_id, meta, extras):
        pass

    def insert_extra(self, artist, title, source):
        return 0


def _run(adapter):
    """Drive the shared engine with a mocked Beatport client (no network, no token)."""
    dummy_bp = MagicMock()
    dummy_bp.search_tracks.return_value = []  # every candidate → not_found
    dummy_client = MagicMock()
    with patch("enrich.engine.bp_api.make_bp_client", return_value=(dummy_bp, dummy_client)):
        enrich_mod.run_enrich_engine(
            adapter, dry_run=False, limit=0, verbose=False,
            threshold=0.72, retry_misses=False,
        )


def test_caffeinate_entered_when_tracks_exist(mock_caffeinate, mock_log_dir):
    track = {"id": 1, "artist": "Artist", "title": "Title", "source": "test"}
    _run(_FakeAdapter([track]))
    assert mock_caffeinate == [True, False], "caffeinate should have been entered and exited"


def test_caffeinate_not_entered_when_no_tracks(mock_caffeinate, mock_log_dir):
    _run(_FakeAdapter([]))
    assert mock_caffeinate == [], "caffeinate must not run when there is nothing to enrich"
