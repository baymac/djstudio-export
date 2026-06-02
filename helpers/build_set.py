"""Curate and sequence ONE DJ set from the analysed library, store it, return its id.

Decoupled from any destination: this writes ONLY to the dj_sets / dj_set_tracks
tables (via detect.db) and prints the new set id. Exporting a stored set to a
Beatport chart / playlist or rekordbox is a separate tool (`dj export set <id>`).

A set is a CURVE OF INTENSITY OVER TIME (an "archetype"), walked greedily so each
next track follows the curve while staying mixable (harmonic + tempo + texture +
variety). Intensity is a POOL-RELATIVE blend of MIK energy, BPM and drum/bass
drive, so "where are we in the night" uses more than one signal:

    intensity = 10 * ( 0.60·norm(mik_nrg) + 0.25·pct(bpm) + 0.15·drive )
        norm(mik_nrg) = (nrg-1)/9          drive = mean(drums_pct, bass_pct)
        pct(bpm), *_pct = percentile rank within the candidate pool (0..1)

Each archetype carries DEFAULT GENRES + a BPM/energy window + a multi-phase curve.
The default genres are a starting point the caller overrides with --genres.

Usage:
    uv run helpers/build_set.py --list-archetypes
    uv run helpers/build_set.py --list-genres [--archetype peak_time]
    uv run helpers/build_set.py --archetype club_night --duration 120   # preview only
    uv run helpers/build_set.py --archetype party --name "Bday Bash" \
        --duration 90 --count 24 --genres "Tech House,Bass House" \
        --date-blend '[{"label":"this year","from":"2026-01-01","ratio":0.9},
                       {"label":"older","to":"2025-12-31","ratio":0.1}]' \
        --save                                     # -> prints "set_id=<n>"

The date blend is any number of release-date ranges, each with a ratio (the set
is filled proportionally). Omit --date-blend for the default 75% ≤1yr / 12.5%
1-2yr / 12.5% older mix.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# repo root on path for `paths`, `detect`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import DB_PATH  # noqa: E402
from detect import db  # noqa: E402


# ===== intensity model ====================================================

# Composite-intensity weights (sum to 1.0). mik_nrg leads (MIK-validated
# perceptual energy); BPM is the strongest secondary dancefloor driver; drive
# (drum+bass presence) separates a banger from a roller at equal nrg/bpm.
W_NRG, W_BPM, W_DRIVE = 0.60, 0.25, 0.15

STEMS = ("vocals", "drums", "bass", "melody")


# ===== date blend (proportional release-date mix) =========================
#
# The release-date control is a list of DATE BUCKETS, each an (optional) ISO
# range + a ratio. The set is filled so each bucket gets ~ratio of the tracks
# (caps shrink to pool supply; any shortfall rolls into buckets that still have
# spare). One window is just a single 100% bucket; a fixed "new/recent/classic"
# split is three buckets. The skill turns free text ("may 2026 50%, jan 2026
# 30%, feb 2026 20%" / "last 2 years 80%, 2010-2020 20%") into this JSON.
#
# today = 2026-06-02. ISO date strings compare lexically; bounds are inclusive
# and the FIRST matching bucket (in list order) claims a track, so order
# narrowest-first when ranges overlap.

@dataclass
class DateBucket:
    label: str
    frm: Optional[str]   # ISO lower bound, inclusive (>=); None = open
    to: Optional[str]    # ISO upper bound, inclusive (<=); None = open
    ratio: float         # share of the set (normalised across buckets)

    def matches(self, release_date: str) -> bool:
        rd = release_date or ""
        if self.frm and rd < self.frm:
            return False
        if self.to and rd > self.to:
            return False
        return True


# Default when the caller passes no --date-blend: 75% within ~1yr, 12.5% 1-2yr,
# 12.5% older. Expressed as date buckets so it shares one code path.
DEFAULT_DATE_BLEND = [
    DateBucket("new (≤1yr)",      "2025-06-02", None,         0.75),
    DateBucket("recent (1-2yr)",       "2024-06-02", "2025-06-02", 0.125),
    DateBucket("classic (>2yr)",       None,         "2024-06-02", 0.125),
]


def _auto_label(frm: Optional[str], to: Optional[str]) -> str:
    if frm and to:
        return f"{frm}..{to}"
    if frm:
        return f"≥{frm}"
    if to:
        return f"≤{to}"
    return "any"


def parse_date_blend(spec: Optional[str]) -> list[DateBucket]:
    """JSON spec -> normalised DateBuckets. Spec is a list of objects with
    `ratio` and optional `from`/`to` (ISO) + `label`. Ratios are renormalised to
    sum to 1. None/empty spec returns the default 75/12.5/12.5 blend."""
    if not spec:
        return [DateBucket(b.label, b.frm, b.to, b.ratio) for b in DEFAULT_DATE_BLEND]
    data = json.loads(spec)
    if not isinstance(data, list) or not data:
        raise ValueError("--date-blend must be a non-empty JSON list of buckets")
    buckets = []
    for d in data:
        ratio = float(d["ratio"])
        if ratio <= 0:
            raise ValueError("each date bucket needs ratio > 0")
        frm, to = d.get("from"), d.get("to")
        buckets.append(DateBucket(d.get("label") or _auto_label(frm, to),
                                   frm, to, ratio))
    total = sum(b.ratio for b in buckets)
    for b in buckets:
        b.ratio /= total
    return buckets


def date_quotas(n: int, buckets: list[DateBucket], supply: list[int]) -> list[int]:
    """Integer per-bucket targets summing to min(n, total supply): largest-
    remainder rounding of n*ratio, capped to each bucket's available tracks, with
    any shortfall refilled into buckets that still have spare."""
    exact = [n * b.ratio for b in buckets]
    q = [int(x) for x in exact]
    rem = n - sum(q)
    for i in sorted(range(len(buckets)), key=lambda i: exact[i] - q[i],
                    reverse=True)[:max(0, rem)]:
        q[i] += 1
    q = [min(q[i], supply[i]) for i in range(len(buckets))]
    while n - sum(q) > 0:
        spare = [(supply[i] - q[i], i) for i in range(len(buckets))
                 if supply[i] - q[i] > 0]
        if not spare:
            break
        spare.sort(key=lambda s: (-s[0], s[1]))
        q[spare[0][1]] += 1
    return q


# ===== data =================================================================

@dataclass
class Track:
    beatport_id: int
    artist: str
    title: str
    bpm: float
    key: str          # Camelot, e.g. "11B"
    nrg: float        # mik_nrg 1-10
    genre: str
    label: str
    release_date: str
    vocals_avg: Optional[float] = None
    drums_avg: Optional[float] = None
    bass_avg: Optional[float] = None
    melody_avg: Optional[float] = None
    # composite intensity (1-10), filled once the candidate pool is known
    intensity: float = 0.0
    # index into the active date blend (set by assign_date_buckets; -1 = no match)
    date_bucket: int = -1


@dataclass
class Phase:
    """One control point on a set's intensity curve at progress t∈[0,1].

    `energy` is the target INTENSITY (1-10, the composite above) at that point.
    Stem fields are the desired emphasis there, each in [-1,+1]: +1 = strongly
    want this stem loud relative to the pool, -1 = quiet, 0 = don't care. This is
    what pulls studio-analyse stem texture into the shape of the night.
    """
    name: str
    t: float
    energy: float
    vocals: float = 0.0
    drums: float = 0.0
    bass: float = 0.0
    melody: float = 0.0


@dataclass
class Archetype:
    key: str
    name: str
    ending: str                 # human note on how it ends
    genres: tuple[str, ...]     # DEFAULT genres (overridable with --genres)
    bpm_lo: float
    bpm_hi: float
    nrg_lo: float
    nrg_hi: float
    curve: list[Phase]
    # suggested harmonic feel for this archetype (overridable with --method /
    # --diversity). Live/party arcs default to playful 'mood'; a radio/mixtape
    # arc wants 'fuzzy' (few key clashes) + low diversity.
    method: str = "mood"
    diversity: float = 0.4


# ----- the catalogue (signed-off curves) ----------------------------------

ARCHETYPES: dict[str, Archetype] = {
    "warmup": Archetype(
        "warmup", "Opener / Warm-Up", "ends mid, hands off to the next DJ",
        ("Deep House", "Melodic House & Techno", "Progressive House",
         "Indie Dance", "Electronica"),
        116, 123, 2, 5,
        [Phase("settle", 0.00, 2.5, melody=.5, vocals=.4, drums=-.4, bass=-.3),
         Phase("deepen", 0.35, 3.5, melody=.4, vocals=.3, drums=-.2),
         Phase("lift",   0.70, 4.5, melody=.2, drums=.2, bass=.2),
         Phase("handoff",1.00, 5.5, drums=.3, bass=.3)],
    ),
    "peak_time": Archetype(
        "peak_time", "Peak Time", "ends high, pulses with rotate-floor breathers",
        ("Tech House", "Bass House", "Mainstage",
         "Techno (Peak Time / Driving)", "House"),
        124, 130, 6, 9,
        [Phase("drive",  0.00, 7.0, drums=.6, bass=.6),
         Phase("peak1",  0.30, 9.0, drums=.8, bass=.7, vocals=-.2),
         Phase("breath", 0.45, 7.8, vocals=.4, melody=.3),
         Phase("peak2",  0.70, 9.3, drums=.8, bass=.8),
         Phase("breath2",0.82, 8.0, vocals=.3, melody=.3),
         Phase("climax", 1.00, 9.5, drums=.9, bass=.9, vocals=-.2)],
    ),
    "late_night": Archetype(
        "late_night", "Late Night / After-Hours", "hypnotic, low-vocal, steady",
        ("Minimal / Deep Tech", "Melodic House & Techno", "Afro House",
         "Tech House"),
        122, 126, 5, 7,
        [Phase("enter", 0.00, 6.0, bass=.6, drums=.4, vocals=-.4),
         Phase("roll",  0.30, 5.5, bass=.6, drums=.3, vocals=-.5),
         Phase("lift",  0.55, 6.5, bass=.7, drums=.5, vocals=-.4),
         Phase("roll2", 0.80, 5.8, bass=.6, drums=.3, vocals=-.5),
         Phase("hypno", 1.00, 6.0, bass=.6, drums=.4, vocals=-.5)],
    ),
    "closing": Archetype(
        "closing", "Closing / Last Dance", "emotional descent, ends low",
        ("Melodic House & Techno", "Progressive House", "Trance (Main Floor)",
         "Electronica"),
        119, 125, 3, 7,
        [Phase("lift",  0.00, 6.5, drums=.3, bass=.3),
         Phase("hold",  0.25, 6.0, melody=.3, vocals=.2),
         Phase("ease",  0.55, 5.0, melody=.5, vocals=.4, drums=-.2),
         Phase("emote", 0.80, 4.0, melody=.7, vocals=.5, drums=-.3),
         Phase("last",  1.00, 3.5, melody=.8, vocals=.5, drums=-.4, bass=-.3)],
    ),
    "club_night": Archetype(
        "club_night", "Full Club Night", "ends high (the night-arc sketch)",
        ("Deep House", "Melodic House & Techno", "Tech House", "House",
         "Afro House", "Progressive House"),
        118, 130, 2, 10,
        [Phase("start",   0.00, 3.0, melody=.5, vocals=.4, drums=-.4, bass=-.4),
         Phase("rise",    0.12, 4.5, melody=.3, vocals=.3, drums=-.2),
         Phase("bump",    0.22, 5.5, melody=.2, drums=.2, bass=.2),
         Phase("dip",     0.32, 4.0, vocals=.4, melody=.4, drums=-.3),
         Phase("climb",   0.45, 7.5, drums=.6, bass=.6, vocals=-.1),
         Phase("plateau", 0.58, 8.3, drums=.7, bass=.7),
         Phase("breather",0.68, 7.3, vocals=.4, melody=.3),
         Phase("plateau2",0.82, 9.0, drums=.8, bass=.8, vocals=-.2),
         Phase("spike",   1.00, 10.0, drums=.9, bass=.9, vocals=-.3)],
    ),
    "sunset": Archetype(
        "sunset", "Sunset / Rooftop", "soft wave, ends low-mid",
        ("Melodic House & Techno", "Deep House", "Afro House", "Indie Dance",
         "Electronica"),
        115, 123, 2, 6,
        [Phase("arrive", 0.00, 3.0, melody=.5, vocals=.3, drums=-.3),
         Phase("warm",   0.30, 4.5, melody=.4, vocals=.3),
         Phase("glow",   0.55, 6.0, melody=.3, drums=.3, bass=.3, vocals=.2),
         Phase("ease",   0.80, 5.0, melody=.4, vocals=.3, drums=-.1),
         Phase("dusk",   1.00, 4.0, melody=.6, vocals=.4, drums=-.3)],
    ),
    "party": Archetype(
        "party", "House Party / Birthday", "sing-along peaks, ends high",
        ("House", "Tech House", "Bass House", "Dance / Pop", "Indie Dance"),
        122, 128, 4, 9,
        [Phase("kick",      0.00, 5.0, vocals=.4, melody=.3),
         Phase("groove",    0.25, 6.5, vocals=.3, drums=.3, bass=.3),
         Phase("singalong", 0.45, 7.5, vocals=.6, melody=.3),
         Phase("breath",    0.58, 6.8, vocals=.4, melody=.3),
         Phase("hype",      0.78, 8.5, drums=.6, bass=.6, vocals=.3),
         Phase("finale",    1.00, 9.0, vocals=.5, drums=.6, bass=.5)],
    ),
    "dark": Archetype(
        "dark", "Dark / Halloween / Warehouse", "tense, bass-driven, ends intense",
        ("Techno (Peak Time / Driving)", "Minimal / Deep Tech", "Tech House",
         "Bass House"),
        124, 132, 4, 9,
        [Phase("intro",   0.00, 4.0, bass=.4, drums=.2, vocals=-.5, melody=-.2),
         Phase("tension", 0.22, 5.5, bass=.6, drums=.4, vocals=-.5),
         Phase("drop1",   0.38, 8.0, drums=.8, bass=.8, vocals=-.4),
         Phase("void",    0.50, 6.0, bass=.6, vocals=-.5, melody=-.3),
         Phase("build",   0.68, 7.5, drums=.7, bass=.7, vocals=-.4),
         Phase("drop2",   0.85, 9.0, drums=.9, bass=.9, vocals=-.5),
         Phase("abyss",   1.00, 9.3, drums=.8, bass=.9, vocals=-.5)],
    ),
    "festival": Archetype(
        "festival", "Festival Mainstage", "multi-drop, euphoric finish",
        ("Mainstage", "Bass House", "Tech House", "House", "Trance (Main Floor)"),
        126, 132, 6, 10,
        [Phase("intro",    0.00, 6.0, drums=.4, bass=.4, melody=.2),
         Phase("build1",   0.20, 7.5, drums=.6, bass=.6),
         Phase("drop1",    0.32, 9.0, drums=.8, bass=.8, vocals=-.1),
         Phase("anthem",   0.48, 7.5, vocals=.5, melody=.5),
         Phase("build2",   0.65, 8.5, drums=.7, bass=.7),
         Phase("drop2",    0.80, 9.5, drums=.9, bass=.9),
         Phase("euphoria", 1.00, 10.0, vocals=.4, melody=.5, drums=.7, bass=.7)],
    ),
    "dinner": Archetype(
        "dinner", "Dinner / Lounge", "low, conversational, flat-gentle",
        ("Electronica", "Deep House", "Melodic House & Techno", "Indie Dance"),
        110, 120, 1, 4,
        [Phase("seat",    0.00, 2.0, melody=.5, vocals=.4, drums=-.6, bass=-.5),
         Phase("ambient", 0.40, 2.5, melody=.6, vocals=.4, drums=-.5, bass=-.4),
         Phase("warm",    0.75, 3.0, melody=.5, vocals=.4, drums=-.4, bass=-.3),
         Phase("close",   1.00, 3.5, melody=.4, vocals=.3, drums=-.3)],
    ),
    "morning_coffee": Archetype(
        "morning_coffee", "Morning Coffee", "bright, mellow, ends soft",
        ("Electronica", "Indie Dance", "Deep House", "Melodic House & Techno"),
        110, 122, 2, 5,
        [Phase("sip",    0.00, 2.5, melody=.5, vocals=.4, drums=-.4, bass=-.4),
         Phase("warm",   0.30, 3.5, melody=.5, vocals=.4, drums=-.2),
         Phase("bright", 0.60, 4.5, melody=.4, vocals=.3, drums=.1),
         Phase("settle", 0.85, 4.0, melody=.5, vocals=.3, drums=-.1),
         Phase("linger", 1.00, 3.5, melody=.5, vocals=.4, drums=-.3)],
    ),
    "radio_mix": Archetype(
        # Broadcast/mixtape feel: hook fast (no dancefloor warm-up — listeners
        # tune in mid-stream), hold a consistent, engaging mid energy with gentle
        # lifts rather than a big arc, stay vocal/melody-forward (hooks +
        # recognizable records), end clean. Pairs with fuzzy mixing + low
        # diversity for the few-key-clashes-as-possible radio sequence.
        "radio_mix", "Radio Mix", "consistent, vocal-led, clean broadcast ending",
        ("Dance / Pop", "House", "Melodic House & Techno", "Tech House",
         "Indie Dance"),
        120, 126, 4, 7,
        [Phase("hook",   0.00, 5.0, vocals=.5, melody=.4),
         Phase("groove", 0.25, 6.0, vocals=.4, melody=.3, drums=.2),
         Phase("lift",   0.50, 6.8, vocals=.4, drums=.3, bass=.3),
         Phase("ease",   0.70, 6.0, vocals=.5, melody=.3),
         Phase("lift2",  0.88, 6.8, vocals=.4, drums=.3, bass=.3),
         Phase("outro",  1.00, 5.5, vocals=.5, melody=.4, drums=-.1)],
        method="fuzzy", diversity=0.2,
    ),
}


# ===== harmonic compatibility (Camelot wheel) =============================
#
# Two mixing METHODS, mirroring DJ.Studio's harmonic modes:
#   fuzzy — prioritise harmonically SAFE transitions, keep key clashes minimal
#           (good for a mixtape / radio mix); bold key jumps stay expensive so
#           the sequence almost never goes off-tone.
#   mood  — EMBRACE energy-changing key moves (boost / diagonal / bold jumps)
#           that excite a live or party floor; only a true tritone clash stays
#           expensive. Harder to pull off live, but more dynamic.
# Each move between two Camelot keys is classified into a RELATIONSHIP, and the
# active method assigns it a penalty (0 = perfect, larger = rougher). The
# --diversity knob (0..1) then layers anti-monotony pressure on top, so the walk
# rotates around the wheel instead of parking on one or two keys (the "so many
# 1A / 2A in a row" problem).

def _parse_camelot(key: str) -> Optional[tuple[int, str]]:
    key = (key or "").strip().upper()
    if len(key) < 2 or key[-1] not in ("A", "B"):
        return None
    try:
        return int(key[:-1]), key[-1]
    except ValueError:
        return None


# relationship keys (a -> b on the Camelot wheel)
REL_MATCH, REL_SCALE, REL_ENERGY = "match", "scale", "energy"
REL_DIAGONAL, REL_BOOST, REL_MOOD, REL_CLASH = (
    "diagonal", "boost", "mood", "clash")


def camelot_step(a: str, b: str) -> Optional[int]:
    """Signed wheel distance a->b in [-5..6] (number ring), or None if unknown."""
    pa, pb = _parse_camelot(a), _parse_camelot(b)
    if not pa or not pb:
        return None
    return ((pb[0] - pa[0] + 6) % 12) - 6


def camelot_relationship(a: str, b: str) -> Optional[str]:
    """Classify the move a->b. None when either key is unparseable."""
    pa, pb = _parse_camelot(a), _parse_camelot(b)
    if not pa or not pb:
        return None
    (na, la), (nb, lb) = pa, pb
    adist = min((nb - na) % 12, (na - nb) % 12)   # 0..6 steps around the wheel
    same_letter = la == lb
    if adist == 0:
        return REL_MATCH if same_letter else REL_SCALE   # same key / relative maj-min
    if same_letter:
        if adist == 1:
            return REL_ENERGY              # ±1: the smooth energy boost/drop
        if adist == 2:
            return REL_BOOST               # ±2: bigger energy boost
        if adist <= 5:
            return REL_MOOD                # bold jump that shifts mood
        return REL_CLASH                   # ±6 tritone
    if adist == 1:
        return REL_DIAGONAL                # diagonal neighbour (±1 + relative)
    if adist <= 5:
        return REL_MOOD
    return REL_CLASH


# per-method penalties (added to the score; lower = better next track)
_FUZZY_PEN = {REL_MATCH: 0.0, REL_SCALE: 0.4, REL_ENERGY: 0.4, REL_DIAGONAL: 1.2,
              REL_BOOST: 1.2, REL_MOOD: 5.0, REL_CLASH: 9.0}
_MOOD_PEN = {REL_MATCH: 0.0, REL_SCALE: 0.3, REL_ENERGY: 0.3, REL_DIAGONAL: 0.7,
             REL_BOOST: 0.7, REL_MOOD: 1.8, REL_CLASH: 6.0}
METHODS = ("fuzzy", "mood")


def harmonic_penalty(prev_key: str, cand_key: str, method: str) -> float:
    rel = camelot_relationship(prev_key, cand_key)
    if rel is None:
        return 0.0                         # unknown key never blocks a mix
    table = _MOOD_PEN if method == "mood" else _FUZZY_PEN
    return table[rel]


_REL_TAG = {REL_MATCH: "=", REL_SCALE: "rel", REL_DIAGONAL: "diag",
            REL_MOOD: "mood", REL_CLASH: "!"}


def rel_tag(prev_key: str, cand_key: str) -> str:
    """Short label for the move into a track, shown in the preview's 'mv' column."""
    rel = camelot_relationship(prev_key, cand_key)
    if rel is None:
        return "?"
    if rel in (REL_ENERGY, REL_BOOST):
        return f"{camelot_step(prev_key, cand_key):+d}"   # +1 / -2 etc.
    return _REL_TAG[rel]


# ===== candidate loading ===================================================

def load_pool(conn: sqlite3.Connection, genres: tuple[str, ...],
              bpm_lo: float, bpm_hi: float, nrg_lo: float, nrg_hi: float,
              ) -> list[Track]:
    """Candidates matching genre + BPM + energy window. Date filtering is applied
    later by assign_date_buckets against the chosen blend (not in SQL), so one
    pool serves any number of arbitrary date ranges."""
    placeholders = ",".join("?" for _ in genres)
    rows = conn.execute(
        f"""SELECT e.beatport_id, e.artist, e.title, e.bpm, a.mik_key, a.mik_nrg,
                   e.genre, e.label, e.release_date,
                   a.vocals_avg, a.drums_avg, a.bass_avg, a.melody_avg
            FROM enriched_tracks e
            JOIN enriched_tracks_analysis a USING(beatport_id)
            WHERE e.genre IN ({placeholders})
              AND e.bpm BETWEEN ? AND ?
              AND a.mik_nrg BETWEEN ? AND ?
              AND a.mik_key IS NOT NULL
              AND e.artist IS NOT NULL AND e.title IS NOT NULL""",
        (*genres, bpm_lo, bpm_hi, nrg_lo, nrg_hi),
    ).fetchall()
    pool: list[Track] = []
    seen_pairs: set[tuple[str, str]] = set()
    for r in rows:
        pair = ((r[1] or "").lower().strip(), (r[2] or "").lower().strip())
        if pair in seen_pairs:
            continue              # collapse same artist+title (remix dupes)
        seen_pairs.add(pair)
        pool.append(Track(int(r[0]), r[1], r[2], float(r[3]), r[4], float(r[5]),
                           r[6], r[7] or "", r[8] or "",
                           vocals_avg=r[9], drums_avg=r[10],
                           bass_avg=r[11], melody_avg=r[12]))
    return pool


def assign_date_buckets(pool: list[Track],
                        buckets: list[DateBucket]) -> list[Track]:
    """Tag each track with the index of the first date bucket it matches and DROP
    tracks outside every bucket. Returns the surviving (in-window) pool."""
    kept: list[Track] = []
    for t in pool:
        idx = next((i for i, b in enumerate(buckets) if b.matches(t.release_date)),
                   -1)
        if idx >= 0:
            t.date_bucket = idx
            kept.append(t)
    return kept


# ===== intensity + percentiles =============================================

def _percentiles(values: list[tuple[float, int]]) -> dict[int, float]:
    """Rank (value, id) pairs into a 0..1 percentile by value. Missing -> 0.5."""
    vals = sorted(values)
    n = len(vals)
    return {bid: (i / (n - 1) if n > 1 else 0.5) for i, (_v, bid) in enumerate(vals)}


def _stem_percentiles(pool: list[Track]) -> dict[str, dict[int, float]]:
    """Per-stem 0..1 percentile of avg-RMS within this pool (unit-agnostic)."""
    return {stem: _percentiles([(getattr(t, f"{stem}_avg"), t.beatport_id)
                                 for t in pool
                                 if getattr(t, f"{stem}_avg") is not None])
            for stem in STEMS}


def assign_intensity(pool: list[Track], pct: dict[str, dict[int, float]]) -> None:
    """Fill each track's composite intensity (1-10), pool-relative. Mutates pool."""
    bpm_pct = _percentiles([(t.bpm, t.beatport_id) for t in pool])
    for t in pool:
        nrg01 = max(0.0, min(1.0, (t.nrg - 1) / 9))
        bp = bpm_pct.get(t.beatport_id, 0.5)
        drive = (pct["drums"].get(t.beatport_id, 0.5)
                 + pct["bass"].get(t.beatport_id, 0.5)) / 2
        t.intensity = 10 * (W_NRG * nrg01 + W_BPM * bp + W_DRIVE * drive)


# ===== greedy sequencing ===================================================

def _curve_at(curve: list[Phase], frac: float) -> Phase:
    """Piecewise-linear interpolation of intensity + stem emphasis at progress
    `frac` in [0, 1] across the curve's control points."""
    if frac <= curve[0].t:
        return curve[0]
    if frac >= curve[-1].t:
        return curve[-1]
    for a, b in zip(curve, curve[1:]):
        if a.t <= frac <= b.t:
            w = (frac - a.t) / (b.t - a.t) if b.t > a.t else 0.0
            lerp = lambda x, y: x + (y - x) * w  # noqa: E731
            return Phase("interp", frac, lerp(a.energy, b.energy),
                         lerp(a.vocals, b.vocals), lerp(a.drums, b.drums),
                         lerp(a.bass, b.bass), lerp(a.melody, b.melody))
    return curve[-1]


def _stem_penalty(t: Track, phase: Phase,
                  pct: dict[str, dict[int, float]]) -> float:
    """Reward tracks whose stem balance matches the phase emphasis. emphasis>0
    wants a high percentile, <0 wants low; negated so a good match lowers score."""
    reward = 0.0
    for stem in STEMS:
        e = getattr(phase, stem)
        if e:
            reward += e * (pct[stem].get(t.beatport_id, 0.5) - 0.5) * 2.0
    return -reward


# scorer weights
W_INTENSITY, W_BPM_SMOOTH, W_STEM = 2.0, 1.0, 1.5
VOCAL_CLASH_PEN = 3.0
SAME_ARTIST_PEN, RECENT_ARTIST_PEN, SAME_LABEL_PEN = 10.0, 4.0, 1.5
VOCAL_HEAVY = 0.75

# key-diversity (scaled by the --diversity knob 0..1): discourage replaying a
# key seen in the last KEY_RECENT_WINDOW tracks, and reward an as-yet-unused key
# so the walk spreads around the wheel instead of camping on one or two keys.
W_KEY_REPEAT, W_KEY_FRESH, KEY_RECENT_WINDOW = 7.0, 2.0, 3


def sequence(arch: Archetype, pool: list[Track], size: int,
             buckets: list[DateBucket], seed_id: Optional[int] = None,
             method: str = "mood", diversity: float = 0.4) -> list[Track]:
    remaining = list(pool)
    by_id = {t.beatport_id: t for t in pool}
    seq: list[Track] = []
    artist_count: dict[str, int] = {}
    used_keys: set[str] = set()
    n = min(size, len(pool))
    if n == 0:
        return seq
    pct = _stem_percentiles(pool)

    # proportional per-date-bucket caps (shrunk to supply, shortfall refilled)
    supply = [sum(1 for t in pool if t.date_bucket == i)
              for i in range(len(buckets))]
    quota = date_quotas(n, buckets, supply)
    bucket_count = [0] * len(buckets)

    def take(t: Track) -> None:
        seq.append(t)
        remaining.remove(t)
        artist_count[t.artist] = artist_count.get(t.artist, 0) + 1
        bucket_count[t.date_bucket] += 1
        used_keys.add(t.key)

    def bucket_open(t: Track) -> bool:
        return bucket_count[t.date_bucket] < quota[t.date_bucket]

    # seed: forced track or the candidate nearest the curve's opening intensity
    seed = by_id.get(seed_id) if seed_id else None
    if seed is None:
        seed = min(remaining, key=lambda t: abs(t.intensity - arch.curve[0].energy))
    take(seed)

    while len(seq) < n and remaining:
        cur = seq[-1]
        recent_artists = {t.artist for t in seq[-2:]}
        recent_keys = {t.key for t in seq[-KEY_RECENT_WINDOW:]}
        phase = _curve_at(arch.curve, len(seq) / (n - 1) if n > 1 else 0.0)
        cur_vocal = pct["vocals"].get(cur.beatport_id, 0.5)
        best: Optional[Track] = None
        best_score = float("inf")
        for c in remaining:
            if artist_count.get(c.artist, 0) >= 2:
                continue
            if not bucket_open(c):
                continue
            score = abs(c.intensity - phase.energy) * W_INTENSITY
            score += abs(c.bpm - cur.bpm) * W_BPM_SMOOTH
            score += _stem_penalty(c, phase, pct) * W_STEM
            if (cur_vocal > VOCAL_HEAVY
                    and pct["vocals"].get(c.beatport_id, 0.5) > VOCAL_HEAVY):
                score += VOCAL_CLASH_PEN
            score += harmonic_penalty(cur.key, c.key, method)
            if diversity > 0:
                if c.key in recent_keys:
                    score += diversity * W_KEY_REPEAT   # anti-monotony
                if c.key not in used_keys:
                    score -= diversity * W_KEY_FRESH    # reward a fresh key
            if c.artist == cur.artist:
                score += SAME_ARTIST_PEN
            elif c.artist in recent_artists:
                score += RECENT_ARTIST_PEN
            if c.label and c.label == cur.label:
                score += SAME_LABEL_PEN
            if score < best_score:
                best_score, best = score, c
        if best is None:                 # caps exhausted; relax to any track
            pickable = [t for t in remaining
                        if artist_count.get(t.artist, 0) < 2] or remaining
            best = min(pickable, key=lambda t: abs(t.intensity - phase.energy))
        take(best)
    return seq


# ===== track-count bounds ==================================================

def count_bounds(duration_min: int) -> tuple[int, int]:
    """max = duration/2, min = duration/5 (a track plays ~2-5 min)."""
    return max(1, duration_min // 5), max(1, duration_min // 2)


def resolve_count(duration_min: int, requested: Optional[int]) -> tuple[int, str]:
    lo, hi = count_bounds(duration_min)
    if requested is None:
        return max(lo, min(hi, round(duration_min / 3.5))), ""
    if requested < lo:
        return lo, f"requested {requested} < min {lo} for {duration_min}min; using {lo}"
    if requested > hi:
        return hi, f"requested {requested} > max {hi} for {duration_min}min; using {hi}"
    return requested, ""


# ===== reporting ============================================================

def _spark(intensity: float) -> str:
    bars = "▁▂▃▄▅▆▇█"
    return bars[max(0, min(7, round((intensity - 1) / 9 * 7)))]


def set_payload(arch: Archetype, seq: list[Track], buckets: list[DateBucket],
                method: str = "mood", diversity: float = 0.4) -> dict:
    """JSON-able view of a built set (for --json preview + audit)."""
    return {
        "archetype": arch.key,
        "name": arch.name,
        "track_count": len(seq),
        "method": method,
        "diversity": diversity,
        "distinct_keys": len({t.key for t in seq}),
        "curve": [{"name": p.name, "t": p.t, "intensity": p.energy}
                  for p in arch.curve],
        "date_blend": [{"label": b.label, "from": b.frm, "to": b.to,
                        "ratio": round(b.ratio, 4),
                        "selected": sum(1 for t in seq if t.date_bucket == i)}
                       for i, b in enumerate(buckets)],
        "tracks": [{"position": i, "beatport_id": t.beatport_id,
                    "artist": t.artist, "title": t.title, "bpm": t.bpm,
                    "key": t.key, "nrg": t.nrg, "intensity": round(t.intensity, 2),
                    "year": t.release_date[:4],
                    "date_bucket": buckets[t.date_bucket].label}
                   for i, t in enumerate(seq, 1)],
    }


def print_set(arch: Archetype, seq: list[Track], buckets: list[DateBucket],
              method: str = "mood", diversity: float = 0.4) -> None:
    if not seq:
        print(f"  (empty — no candidates matched for archetype {arch.key})")
        return
    ints = [t.intensity for t in seq]
    bpms = [t.bpm for t in seq]
    distinct_keys = len({t.key for t in seq})
    print(f"\n{'='*78}")
    print(f"  {arch.name}  [{arch.key}]  —  {arch.ending}")
    arc = "→".join(f"{p.energy:.0f}" for p in arch.curve)
    print(f"  {len(seq)} tracks | BPM {min(bpms):.0f}-{max(bpms):.0f} | "
          f"intensity {min(ints):.1f}-{max(ints):.1f} | curve {arc}")
    print(f"  harmonic: {method} method | diversity {diversity:.2f} | "
          f"{distinct_keys}/{len(seq)} distinct keys")
    mix = "  ".join(f"[{i+1}] {b.label} {sum(1 for t in seq if t.date_bucket==i)}"
                    f"/{round(b.ratio*len(seq))}" for i, b in enumerate(buckets))
    print(f"  date mix (got/target):  {mix}")
    print(f"{'='*78}")
    print(f"  {'#':>2} {'b':>1} {'int':>4} {'nrg':>3} {'key':>4} {'mv':>4} {'bpm':>4}  "
          f"artist — title  [year]")
    for i, t in enumerate(seq, 1):
        yr = t.release_date[:4] if t.release_date else "????"
        mv = "—" if i == 1 else rel_tag(seq[i - 2].key, t.key)
        print(f"  {i:>2} {t.date_bucket+1:>1} {_spark(t.intensity)}{t.intensity:>3.1f} "
              f"{t.nrg:>3.0f} {t.key:>4} {mv:>4} {t.bpm:>4.0f}  "
              f"{t.artist} — {t.title}  [{yr}]")


# ===== cli ==================================================================

def _list_archetypes() -> None:
    print("Archetypes (key — name — ending | default genres):")
    for a in ARCHETYPES.values():
        arc = "→".join(f"{p.energy:.0f}" for p in a.curve)
        print(f"  {a.key:15} {a.name:28} curve {arc:18} {a.ending}")
        print(f"  {'':15} genres: {', '.join(a.genres)}  | BPM {a.bpm_lo:.0f}-"
              f"{a.bpm_hi:.0f} nrg {a.nrg_lo:.0f}-{a.nrg_hi:.0f} | "
              f"{a.method} mix, diversity {a.diversity:.1f}")


def _list_genres(conn: sqlite3.Connection, arch: Optional[Archetype]) -> None:
    rows = conn.execute(
        """SELECT e.genre, COUNT(*) c
           FROM enriched_tracks e JOIN enriched_tracks_analysis a USING(beatport_id)
           WHERE a.mik_nrg IS NOT NULL AND a.mik_key IS NOT NULL
           GROUP BY e.genre HAVING c > 10 ORDER BY c DESC""").fetchall()
    defaults = set(arch.genres) if arch else set()
    print("Genres in the analysed library (* = default for this archetype):")
    for genre, c in rows:
        mark = "*" if genre in defaults else " "
        print(f"  {mark} {genre:35} {c:>5}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archetype", help="set archetype key (see --list-archetypes)")
    ap.add_argument("--name", help="set name (required with --save)")
    ap.add_argument("--mood", default="", help="free-text mood/setting (stored)")
    ap.add_argument("--duration", type=int, help="set duration in minutes")
    ap.add_argument("--count", type=int,
                    help="target track count (clamped to [duration/5, duration/2])")
    ap.add_argument("--genres", help="comma-separated genres (overrides archetype defaults)")
    ap.add_argument("--date-blend",
                    help='JSON list of {"from","to","ratio","label"} release-date '
                         'buckets, e.g. \'[{"label":"May 2026","from":"2026-05-01",'
                         '"to":"2026-05-31","ratio":0.5},{"label":"2024","from":'
                         '"2024-01-01","to":"2024-12-31","ratio":0.5}]\'. '
                         "Omit for the default 75/12.5/12.5 new/recent/classic mix.")
    ap.add_argument("--method", choices=METHODS, default=None,
                    help="harmonic mixing method: 'fuzzy' (safe, minimal key "
                         "clashes — mixtape/radio) or 'mood' (playful, embraces "
                         "energy-changing key moves — live/party). Defaults to the "
                         "archetype's suggested method.")
    ap.add_argument("--diversity", type=float, default=None,
                    help="key-diversity 0..1: anti-monotony pressure that rotates "
                         "the wheel instead of camping on one or two keys. Higher "
                         "= more playful / more distinct keys. Defaults to the "
                         "archetype's suggested diversity.")
    ap.add_argument("--exclude-used", action="store_true",
                    help="exclude tracks already used in ANY previously-built set "
                         "(no repeats across sets). When rebuilding this same "
                         "name+archetype, its own current tracks are NOT excluded. "
                         "Omit to allow tracks to recur across sets.")
    ap.add_argument("--seed-id", type=int, help="force this beatport_id first")
    ap.add_argument("--json", action="store_true", help="emit the built set as JSON")
    ap.add_argument("--save", action="store_true", help="persist to dj_sets, print set_id")
    ap.add_argument("--list-archetypes", action="store_true")
    ap.add_argument("--list-genres", action="store_true")
    args = ap.parse_args()

    if args.list_archetypes:
        _list_archetypes()
        return

    db.migrate()
    conn = sqlite3.connect(DB_PATH)
    try:
        arch_opt = ARCHETYPES.get(args.archetype) if args.archetype else None

        if args.list_genres:
            _list_genres(conn, arch_opt)
            return

        if not args.archetype:
            ap.error("--archetype is required (see --list-archetypes)")
        if arch_opt is None:
            ap.error(f"unknown archetype {args.archetype!r} (see --list-archetypes)")
        arch = arch_opt
        if not args.duration:
            ap.error("--duration (minutes) is required")

        count, warn = resolve_count(args.duration, args.count)
        if warn:
            print(f"[count] {warn}", file=sys.stderr)

        genres = (tuple(g.strip() for g in args.genres.split(",") if g.strip())
                  if args.genres else arch.genres)
        try:
            buckets = parse_date_blend(args.date_blend)
        except (ValueError, json.JSONDecodeError, KeyError) as e:
            ap.error(f"bad --date-blend: {e}")

        pool = load_pool(conn, genres, arch.bpm_lo, arch.bpm_hi,
                         arch.nrg_lo, arch.nrg_hi)
        if not pool:
            print("No candidates matched. Widen genres or the BPM/energy window.",
                  file=sys.stderr)
            sys.exit(1)
        pool = assign_date_buckets(pool, buckets)
        if not pool:
            print("No candidates fall in any date bucket. Widen the date blend.",
                  file=sys.stderr)
            sys.exit(1)
        excluded_used = 0
        if args.exclude_used:
            used = db.used_beatport_ids(args.name, arch.key)
            before = len(pool)
            pool = [t for t in pool if t.beatport_id not in used]
            excluded_used = before - len(pool)
            if not pool:
                print("Every in-window candidate is already used in a past set. "
                      "Drop --exclude-used or widen genres/dates.", file=sys.stderr)
                sys.exit(1)
        method = args.method or arch.method
        diversity = args.diversity if args.diversity is not None else arch.diversity
        if not 0.0 <= diversity <= 1.0:
            ap.error("--diversity must be between 0.0 and 1.0")
        assign_intensity(pool, _stem_percentiles(pool))
        seq = sequence(arch, pool, count, buckets, seed_id=args.seed_id,
                       method=method, diversity=diversity)

        if args.json:
            print(json.dumps(set_payload(arch, seq, buckets, method=method,
                                         diversity=diversity), indent=2))
        else:
            print_set(arch, seq, buckets, method=method, diversity=diversity)
            used_note = (f" ({excluded_used} excluded as already-used)"
                         if args.exclude_used else "")
            print(f"\n  pool: {len(pool)} in-window candidates{used_note} -> "
                  f"{len(seq)} selected")

        if args.save:
            if not args.name:
                ap.error("--name is required with --save")
            params = {
                "mood": args.mood, "duration_min": args.duration,
                "count": count, "genres": list(genres),
                "method": method, "diversity": diversity,
                "exclude_used": args.exclude_used,
                "date_blend": [{"label": b.label, "from": b.frm, "to": b.to,
                                "ratio": b.ratio} for b in buckets],
                "curve": [{"name": p.name, "t": p.t, "intensity": p.energy}
                          for p in arch.curve],
            }
            set_id = db.record_built_set(args.name, arch.key,
                                         [t.beatport_id for t in seq], params)
            print(f"set_id={set_id}")
        elif not args.json:
            print("  (preview only — add --save --name \"...\" to store)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
