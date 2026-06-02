"""Tests for export/export_set.py — set resolution + destination dispatch.

No network, no real dj.db / Beatport / rekordbox: a temp DB holds the set, and
the three push functions are monkeypatched so we only assert that export_set
resolves the set and dispatches the right tracks (in order) to the right place.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import detect.db as db  # noqa: E402
from export import export_set as es  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.migrate()
    return path


def _make_set(name="My Set", archetype="party", ids=(101, 102, 103), params=None):
    params = params or {"mood": "birthday", "duration_min": 90}
    return db.record_built_set(name, archetype, list(ids), params)


# ----- default chart description -------------------------------------------

def test_default_chart_description_from_params(tmp_db):
    sid = _make_set(params={"mood": "rooftop sunset", "duration_min": 120})
    header = db.get_set(sid)
    desc = es._default_chart_description(header, {"mood": "rooftop sunset", "duration_min": 120})
    assert "rooftop sunset" in desc and "120-min set" in desc and "[party]" in desc


def test_default_chart_description_archetype_only(tmp_db):
    sid = _make_set(params={})
    header = db.get_set(sid)
    assert es._default_chart_description(header, {}) == "[party]"


# ----- guard rails ---------------------------------------------------------

def test_unknown_destination_returns_false(tmp_db):
    sid = _make_set()
    assert es.export_set(sid, "spotify") is False


def test_missing_set_returns_false(tmp_db):
    assert es.export_set(99999, "bp_chart") is False


def test_empty_set_returns_false(tmp_db):
    sid = _make_set(ids=())
    assert es.export_set(sid, "bp_playlist") is False


# ----- dispatch ------------------------------------------------------------

def test_bp_playlist_dispatch_passes_ordered_ids(tmp_db, monkeypatch):
    sid = _make_set(name="Peak", ids=(301, 302, 303))
    calls = {}

    def fake_push(beatport_ids, name, *, dry_run, console):
        calls["ids"] = list(beatport_ids)
        calls["name"] = name
        calls["dry_run"] = dry_run

    monkeypatch.setattr("export.to_beatport.push_to_beatport", fake_push)
    assert es.export_set(sid, "bp_playlist", dry_run=True) is True
    assert calls["ids"] == [301, 302, 303]
    assert calls["name"] == "Peak"          # defaults to the set's name
    assert calls["dry_run"] is True


def test_bp_chart_dispatch_uses_default_description(tmp_db, monkeypatch):
    sid = _make_set(name="Sunset", params={"mood": "rooftop", "duration_min": 60})
    calls = {}

    def fake_push(beatport_ids, name, *, description, dry_run, console):
        calls["ids"] = list(beatport_ids)
        calls["name"] = name
        calls["description"] = description

    monkeypatch.setattr("export.to_beatport.push_to_beatport_chart", fake_push)
    assert es.export_set(sid, "bp_chart") is True
    assert calls["name"] == "Sunset"
    assert "rooftop" in calls["description"]


def test_name_override_wins(tmp_db, monkeypatch):
    sid = _make_set(name="Stored Name")
    calls = {}
    monkeypatch.setattr(
        "export.to_beatport.push_to_beatport",
        lambda ids, name, *, dry_run, console: calls.update(name=name),
    )
    es.export_set(sid, "bp_playlist", name="Override")
    assert calls["name"] == "Override"


def test_rekordbox_dispatch_fetches_full_rows(tmp_db, monkeypatch):
    sid = _make_set(name="RB Set", ids=(401, 402))
    calls = {}

    def fake_fetch(ids):
        return [{"beatport_id": b} for b in ids]

    def fake_push(rows, name, *, dry_run, console):
        calls["rows"] = list(rows)
        calls["name"] = name

    monkeypatch.setattr("playlist.query.fetch_full_rows", fake_fetch)
    monkeypatch.setattr("export.to_rekordbox.push_to_rekordbox", fake_push)
    assert es.export_set(sid, "rekordbox", dry_run=True) is True
    assert [r["beatport_id"] for r in calls["rows"]] == [401, 402]
    assert calls["name"] == "RB Set"
