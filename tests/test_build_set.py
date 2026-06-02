"""Tests for helpers/build_set.py (pure curation logic) + detect.db.record_built_set.

No network, no real dj.db: pure functions run on synthetic pools, and the one
storage test uses a temp DB (matching tests/test_detect_db.py).
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

import build_set as bs  # noqa: E402
import detect.db as db  # noqa: E402


# ----- track-count bounds --------------------------------------------------

def test_count_bounds_are_duration_over_5_and_2():
    assert bs.count_bounds(60) == (12, 30)
    assert bs.count_bounds(90) == (18, 45)
    assert bs.count_bounds(120) == (24, 60)


def test_resolve_count_clamps_below_min_and_above_max():
    lo, _ = bs.resolve_count(60, 5)      # 5 < min 12
    assert lo == 12
    hi, _ = bs.resolve_count(60, 100)    # 100 > max 30
    assert hi == 30
    ok, warn = bs.resolve_count(60, 20)  # in range
    assert ok == 20 and warn == ""


def test_resolve_count_default_is_within_bounds():
    n, _ = bs.resolve_count(60, None)
    lo, hi = bs.count_bounds(60)
    assert lo <= n <= hi


# ----- harmonic compatibility ----------------------------------------------

@pytest.mark.parametrize("a,b,rel", [
    ("8A", "8A", bs.REL_MATCH),      # same key
    ("8A", "8B", bs.REL_SCALE),      # relative major/minor
    ("8A", "9A", bs.REL_ENERGY),     # adjacent number, same letter
    ("12A", "1A", bs.REL_ENERGY),    # wheel wrap 12<->1
    ("8A", "10A", bs.REL_BOOST),     # two steps, same letter
    ("8A", "9B", bs.REL_DIAGONAL),   # diagonal neighbour
    ("8A", "11A", bs.REL_MOOD),      # bold jump
    ("8A", "2A", bs.REL_CLASH),      # tritone (±6)
    ("", "8A", None),                # unknown key — unclassified
])
def test_camelot_relationship(a, b, rel):
    assert bs.camelot_relationship(a, b) == rel


def test_camelot_step_signed_and_wraps():
    assert bs.camelot_step("8A", "9A") == 1
    assert bs.camelot_step("8A", "6A") == -2
    assert bs.camelot_step("12A", "1A") == 1     # wraps forward
    assert bs.camelot_step("1A", "12A") == -1    # wraps back
    assert bs.camelot_step("", "8A") is None


def test_mood_is_more_permissive_than_fuzzy():
    # an adventurous "mood" jump is cheap under mood, expensive under fuzzy;
    # a same-key match costs nothing under either method.
    assert bs.harmonic_penalty("8A", "11A", "mood") < \
        bs.harmonic_penalty("8A", "11A", "fuzzy")
    assert bs.harmonic_penalty("8A", "8A", "mood") == 0.0
    assert bs.harmonic_penalty("8A", "8A", "fuzzy") == 0.0
    assert bs.harmonic_penalty("", "8A", "fuzzy") == 0.0   # unknown never blocks


# ----- archetypes ----------------------------------------------------------

def test_radio_mix_archetype_defaults_to_fuzzy_low_diversity():
    radio = bs.ARCHETYPES["radio_mix"]
    assert radio.method == "fuzzy"
    assert radio.diversity <= 0.3          # clash-minimal radio sequence
    # live/party archetypes keep the playful default
    assert bs.ARCHETYPES["party"].method == "mood"


def test_all_archetype_curves_span_t0_to_t1():
    for a in bs.ARCHETYPES.values():
        assert a.curve[0].t == 0.0
        assert a.curve[-1].t == 1.0
        assert a.method in bs.METHODS


# ----- curve interpolation -------------------------------------------------

def test_curve_at_interpolates_and_clamps():
    curve = [bs.Phase("a", 0.0, 2.0), bs.Phase("b", 1.0, 8.0)]
    assert bs._curve_at(curve, 0.0).energy == 2.0
    assert bs._curve_at(curve, 1.0).energy == 8.0
    assert bs._curve_at(curve, 0.5).energy == pytest.approx(5.0)
    assert bs._curve_at(curve, -1).energy == 2.0   # clamps low
    assert bs._curve_at(curve, 2).energy == 8.0    # clamps high


# ----- catalogue integrity -------------------------------------------------

def test_catalogue_has_expected_keys_including_morning_coffee():
    assert "morning_coffee" in bs.ARCHETYPES
    assert len(bs.ARCHETYPES) >= 11


def test_every_archetype_is_well_formed():
    for key, a in bs.ARCHETYPES.items():
        assert a.genres, f"{key} has no default genres"
        assert a.bpm_lo < a.bpm_hi
        assert a.nrg_lo <= a.nrg_hi
        ts = [p.t for p in a.curve]
        assert ts == sorted(ts), f"{key} curve t not ascending"
        assert ts[0] == 0.0 and ts[-1] == 1.0, f"{key} curve must span 0..1"
        for p in a.curve:
            assert 1.0 <= p.energy <= 10.0, f"{key}/{p.name} intensity out of range"
            for stem in bs.STEMS:
                assert -1.0 <= getattr(p, stem) <= 1.0


def test_intensity_weights_sum_to_one():
    assert bs.W_NRG + bs.W_BPM + bs.W_DRIVE == pytest.approx(1.0)


# ----- composite intensity -------------------------------------------------

def _track(bid, nrg, bpm, key="8A", artist=None, rd="2026-01-01",
           drums=0.5, bass=0.5):
    return bs.Track(bid, artist or f"A{bid}", f"T{bid}", float(bpm), key,
                    float(nrg), "Tech House", f"L{bid}", rd,
                    vocals_avg=0.5, drums_avg=drums, bass_avg=bass, melody_avg=0.5)


def test_assign_intensity_in_range_and_monotone_with_nrg():
    pool = [_track(i, nrg=n, bpm=120 + n) for i, n in enumerate(range(1, 11))]
    bs.assign_intensity(pool, bs._stem_percentiles(pool))
    for t in pool:
        assert 0.0 <= t.intensity <= 10.0
    # higher nrg (and bpm) => higher composite intensity, all else equal
    by_nrg = sorted(pool, key=lambda t: t.nrg)
    assert by_nrg[0].intensity < by_nrg[-1].intensity


# ----- sequencing ----------------------------------------------------------

ANY_DATES = [bs.DateBucket("any", None, None, 1.0)]


def _varied_pool(n=24, buckets=ANY_DATES):
    keys = ["8A", "8B", "9A", "7A", "9B", "10A"]
    pool = []
    for i in range(n):
        pool.append(_track(i, nrg=1 + (i % 10), bpm=120 + (i % 8),
                            key=keys[i % len(keys)],
                            artist=f"Artist{i % 12}",   # forces some repeats
                            rd="2026-01-01"))
    pool = bs.assign_date_buckets(pool, buckets)
    bs.assign_intensity(pool, bs._stem_percentiles(pool))
    return pool


def test_sequence_returns_count_no_dups_max_two_per_artist():
    pool = _varied_pool(24)
    arch = bs.ARCHETYPES["peak_time"]
    seq = bs.sequence(arch, pool, size=10, buckets=ANY_DATES)
    assert len(seq) == 10
    ids = [t.beatport_id for t in seq]
    assert len(set(ids)) == len(ids)               # no duplicates
    from collections import Counter
    counts = Counter(t.artist for t in seq)
    assert max(counts.values()) <= 2               # max 2 tracks per artist


def test_sequence_caps_at_pool_size():
    pool = _varied_pool(6)
    seq = bs.sequence(bs.ARCHETYPES["warmup"], pool, size=20, buckets=ANY_DATES)
    assert len(seq) == 6


# ----- date blend ----------------------------------------------------------

def test_parse_date_blend_default_is_75_12_12():
    b = bs.parse_date_blend(None)
    assert [round(x.ratio, 3) for x in b] == [0.75, 0.125, 0.125]


def test_parse_date_blend_normalises_ratios():
    spec = '[{"from":"2026-05-01","to":"2026-05-31","ratio":5},' \
           ' {"from":"2026-01-01","to":"2026-01-31","ratio":3},' \
           ' {"from":"2026-02-01","to":"2026-02-28","ratio":2}]'
    b = bs.parse_date_blend(spec)
    assert [round(x.ratio, 2) for x in b] == [0.5, 0.3, 0.2]
    assert b[0].label == "May 2026" or b[0].frm == "2026-05-01"


def test_date_bucket_matches_bounds():
    bk = bs.DateBucket("may", "2026-05-01", "2026-05-31", 1.0)
    assert bk.matches("2026-05-15")
    assert not bk.matches("2026-06-01")
    assert not bk.matches("2026-04-30")


def test_assign_date_buckets_drops_out_of_window_and_tags():
    buckets = [bs.DateBucket("2026", "2026-01-01", "2026-12-31", 0.5),
               bs.DateBucket("2024", "2024-01-01", "2024-12-31", 0.5)]
    pool = [_track(1, 5, 124, rd="2026-03-01"),
            _track(2, 5, 124, rd="2024-07-01"),
            _track(3, 5, 124, rd="2025-01-01")]   # in neither bucket
    kept = bs.assign_date_buckets(pool, buckets)
    assert {t.beatport_id for t in kept} == {1, 2}
    assert {t.date_bucket for t in kept} == {0, 1}


def test_date_quotas_proportional_and_supply_capped():
    buckets = [bs.DateBucket("a", None, None, 0.5),
               bs.DateBucket("b", None, None, 0.3),
               bs.DateBucket("c", None, None, 0.2)]
    # ample supply -> proportional
    assert sum(bs.date_quotas(10, buckets, [10, 10, 10])) == 10
    assert bs.date_quotas(10, buckets, [10, 10, 10]) == [5, 3, 2]
    # bucket b starved -> its shortfall refills into buckets with spare
    q = bs.date_quotas(10, buckets, [10, 1, 10])
    assert sum(q) == 10 and q[1] == 1


def test_date_blend_fills_proportionally_end_to_end():
    buckets = [bs.DateBucket("2026", "2026-01-01", "2026-12-31", 0.5),
               bs.DateBucket("2024", "2024-01-01", "2024-12-31", 0.5)]
    pool = ([_track(i, 5, 124, key="8A", artist=f"X{i}", rd="2026-06-01")
             for i in range(10)]
            + [_track(100 + i, 5, 124, key="8A", artist=f"Y{i}", rd="2024-06-01")
               for i in range(10)])
    pool = bs.assign_date_buckets(pool, buckets)
    bs.assign_intensity(pool, bs._stem_percentiles(pool))
    seq = bs.sequence(bs.ARCHETYPES["peak_time"], pool, size=8, buckets=buckets)
    from collections import Counter
    by_bucket = Counter(t.date_bucket for t in seq)
    assert by_bucket[0] == 4 and by_bucket[1] == 4   # 50/50 of 8


# ----- storage: record_built_set (temp DB) ---------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.migrate()
    return path


def test_record_built_set_stores_params_and_replaces(tmp_db):
    params = {"mood": "birthday", "duration_min": 90, "count": 3,
              "genres": ["House"],
              "date_blend": [{"label": "2026", "from": "2026-01-01",
                              "to": None, "ratio": 1.0}],
              "curve": [{"name": "k", "t": 0.0, "intensity": 5.0}]}
    sid = db.record_built_set("Bday", "party", [101, 102, 103], params)

    row = db.get_set(sid)
    assert row["name"] == "Bday" and row["type"] == "party"
    import json
    assert json.loads(row["params_json"])["mood"] == "birthday"
    assert [r["beatport_id"] for r in db.tracks_in_set_id(sid)] == [101, 102, 103]

    # rebuild same name+archetype REPLACES (same id, fresh tracks)
    sid2 = db.record_built_set("Bday", "party", [201, 202], params)
    assert sid2 == sid
    assert [r["beatport_id"] for r in db.tracks_in_set_id(sid)] == [201, 202]
    # exactly one row for this (name, type)
    con = sqlite3.connect(tmp_db)
    n = con.execute("SELECT COUNT(*) FROM dj_sets WHERE name='Bday' AND type='party'").fetchone()[0]
    con.close()
    assert n == 1


def test_used_beatport_ids_excludes_self_when_rebuilding(tmp_db):
    params = {"curve": []}
    db.record_built_set("Set A", "party", [1, 2, 3], params)
    db.record_built_set("Set B", "warmup", [3, 4, 5], params)

    # everything used across all sets
    assert db.used_beatport_ids() == {1, 2, 3, 4, 5}
    # rebuilding "Set A"/party must not count its own current tracks as used
    assert db.used_beatport_ids("Set A", "party") == {3, 4, 5}
    # an unrelated name still sees every used id
    assert db.used_beatport_ids("New Set", "party") == {1, 2, 3, 4, 5}
