"""Tests for export/cli.py `_dispatch_query` — the SQL-curated push that moved
from `dj playlist` into `dj export beatport|rekordbox`.

No network: run_user_query / fetch_full_rows and the push functions are
monkeypatched; we assert the query result is routed to the right destination.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import export.cli as ecli  # noqa: E402


def _args(query="SELECT beatport_id FROM enriched_tracks", name="My List",
          dry_run=False):
    return types.SimpleNamespace(query=query, name=name, dry_run=dry_run)


def test_beatport_verb_pushes_query_ids(monkeypatch):
    calls = {}
    monkeypatch.setattr("playlist.query.run_user_query", lambda q: [11, 22, 33])
    monkeypatch.setattr("playlist.query.fetch_full_rows",
                        lambda ids: [{"beatport_id": b} for b in ids])
    monkeypatch.setattr(
        "export.to_beatport.push_to_beatport",
        lambda ids, name, *, dry_run, console: calls.update(
            ids=list(ids), name=name, dry_run=dry_run),
    )
    ecli._dispatch_query(_args(name="Peak", dry_run=True), "beatport")
    assert calls["ids"] == [11, 22, 33]
    assert calls["name"] == "Peak" and calls["dry_run"] is True


def test_rekordbox_verb_pushes_full_rows(monkeypatch):
    calls = {}
    monkeypatch.setattr("playlist.query.run_user_query", lambda q: [7, 8])
    monkeypatch.setattr("playlist.query.fetch_full_rows",
                        lambda ids: [{"beatport_id": b, "artist": "A"} for b in ids])
    monkeypatch.setattr(
        "export.to_rekordbox.push_to_rekordbox",
        lambda rows, name, *, dry_run, console: calls.update(
            rows=list(rows), name=name),
    )
    ecli._dispatch_query(_args(name="RB"), "rekordbox")
    assert [r["beatport_id"] for r in calls["rows"]] == [7, 8]
    assert calls["name"] == "RB"


def test_empty_query_result_pushes_nothing(monkeypatch):
    pushed = {"called": False}
    monkeypatch.setattr("playlist.query.run_user_query", lambda q: [])
    monkeypatch.setattr(
        "export.to_beatport.push_to_beatport",
        lambda *a, **k: pushed.update(called=True),
    )
    ecli._dispatch_query(_args(), "beatport")
    assert pushed["called"] is False


def test_bad_query_exits(monkeypatch):
    def boom(q):
        raise ValueError("must SELECT beatport_id")
    monkeypatch.setattr("playlist.query.run_user_query", boom)
    with pytest.raises(SystemExit):
        ecli._dispatch_query(_args(), "beatport")
