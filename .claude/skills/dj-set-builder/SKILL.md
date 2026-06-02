---
name: dj-set-builder
description: >-
  Interactively curate and sequence a DJ set from the analysed library using an
  energy-curve archetype, then store it in the dj_sets DB and return its id. Use
  when the user asks to "build a set", "make a set for <occasion/mood>", "warm-up
  / peak-time / closing / club-night / party / sunset set", "sequence a set",
  "energy arc / rotate the dance floor", or to store/update a curated set. The
  engine is helpers/build_set.py; storage + edits live in detect/db.py. Export to
  a Beatport chart/playlist or rekordbox is a SEPARATE tool, not this skill.
---

# DJ Set Builder

Build a set the way a DJ plans a slot: pick the **shape of intensity over time**
(an archetype), then walk the library so each next track follows that shape while
staying mixable (harmonic + tempo + texture + variety) and well-blended (familiar
+ gems, mostly fresh releases). The result is stored as a `dj_set` with a stable
**id** the user can query and edit. This skill **does not export** — that's
`dj export set <id> --to ...` (a separate CLI).

You are the interactive layer. The engine (`helpers/build_set.py`) is a
deterministic, flag-driven script. Gather preferences by asking, resolve them to
flags, **preview**, then **save**.

## The interview (ask in this order; one topic at a time)

1. **Name** — the set name. (May be given as the skill argument.)
2. **Mood / setting** — free text: "friends' birthday party", "halloween opening",
   "club closing", "sunday brunch", "rooftop sunset". Map it to the best-fit
   **archetype** (run `uv run helpers/build_set.py --list-archetypes`). Show the
   user the archetype you picked, its curve, and 1–2 alternatives; let them
   confirm or override. Archetype keys:
   `warmup, peak_time, late_night, closing, club_night, sunset, party, dark,
   festival, dinner, morning_coffee, radio_mix`.
   Mapping examples: birthday/friends → `party`; halloween/warehouse → `dark`;
   club closing → `closing`; brunch/wake-up → `morning_coffee`; rooftop → `sunset`;
   radio show / broadcast / mixtape / podcast → `radio_mix`.
3. **Duration** (minutes). From it the track-count bounds are
   **max = duration/2, min = duration/5** (a track plays ~2–5 min).
4. **Track count** — ask their preference; it is clamped to `[min, max]` and the
   engine warns if you pass something outside. If they have no preference, omit
   `--count` (defaults to ~duration/3.5).
5. **Genres** — every archetype has **default genres**. Show them, plus the live
   library counts (`--list-genres --archetype <key>`, `*` marks defaults). Suggest
   genres to include or exclude for their mood, but **the user's choice is final** —
   pass exactly what they approve via `--genres "A,B,C"`. If they're happy with the
   defaults, omit `--genres`.
6. **Release dates** — free text → a **date blend**: any number of date ranges,
   each with a ratio (the set is filled proportionally). Convert their answer to
   ISO ranges and pass `--date-blend '<json list>'`, where each bucket is
   `{"label","from","to","ratio"}` (`from`/`to` optional/open; ratios are
   renormalised). Today is 2026-06-02, so "last year" = from `2025-06-02`.
   - "May 2026 50%, Jan 2026 30%, Feb 2026 20%" →
     `[{"label":"May 2026","from":"2026-05-01","to":"2026-05-31","ratio":0.5},
       {"label":"Jan 2026","from":"2026-01-01","to":"2026-01-31","ratio":0.3},
       {"label":"Feb 2026","from":"2026-02-01","to":"2026-02-28","ratio":0.2}]`
   - "this year 90%, older 10%" →
     `[{"from":"2026-01-01","ratio":0.9},{"to":"2025-12-31","ratio":0.1}]`
   - "last 2 years 80%, 2010-2020 20%" →
     `[{"from":"2024-06-02","ratio":0.8},
       {"from":"2010-01-01","to":"2020-12-31","ratio":0.2}]`
   - "just May 2026" → a single 100% bucket
     `[{"from":"2026-05-01","to":"2026-05-31","ratio":1}]`.
   - "anything" / "mix old and new" → pass **nothing** (the engine applies the
     default 75% ≤1yr / 12.5% 1–2yr / 12.5% older blend).
   Order narrowest range first when ranges overlap (the first matching bucket
   claims a track). Tracks outside every bucket are excluded.
7. **Harmonic feel** — two controls that shape how keys move (DJ.Studio's
   Camelot modes). Each archetype carries a sensible default; only ask if the
   user wants to steer, or if the archetype's default doesn't fit their intent.
   - **Method** (`--method`): `mood` (playful — embraces energy-changing key
     jumps that lift a live/party floor) or `fuzzy` (clash-minimal, smoothest
     blends — the right call for a mixtape / radio mix). Live/party arcs default
     to `mood`; `radio_mix` defaults to `fuzzy`.
   - **Diversity** (`--diversity`, 0–1): anti-monotony pressure that rotates the
     Camelot wheel instead of camping on one or two keys. Ask on a **0–10 scale**
     and divide by 10. Low (0–3) = mostly same/adjacent keys, very smooth; mid
     (4–6) = a noticeable journey, all moves still safe; high (7–10) = bold mood
     jumps + diagonals, max key variety, harder transitions. Default ≈4.
   Omit both flags to take the archetype's defaults. The preview prints the
   resolved `method`, `diversity`, the `N/total distinct keys` count, and a `mv`
   column showing each move (`=`, `+1`/`-2` energy steps, `diag`, `mood`).
8. **Repeats across sets** — ask whether to **reuse tracks that already appear in
   past sets**, or keep this set fresh. Default is to allow repeats (omit the
   flag). If they want no repeats, pass `--exclude-used`: it drops any track
   already in ANY stored set from the candidate pool. Rebuilding the *same*
   name+archetype does **not** exclude that set's own current tracks (it's being
   replaced), so re-runs still work. The preview reports how many candidates were
   excluded as already-used; if it empties the pool, widen genres/dates or drop
   the flag.

## Preview, then save

Run a **preview first** (no `--save`) and show the user the sequence + the
intensity sparkline + recency tags + the candidate-pool size:

```bash
uv run helpers/build_set.py --archetype party --duration 90 --count 24 \
    --genres "House,Tech House,Bass House"          # preview
```

If they want changes (different archetype, genres, count, dates), re-run the
preview with the tweaked flags. When they approve, **save** (add `--name` +
`--save`); the engine prints `set_id=<n>`:

```bash
uv run helpers/build_set.py --archetype party --name "Maya's Bday" --mood "friends birthday" \
    --duration 90 --count 24 --genres "House,Tech House,Bass House" --save
```

Report the **set id** and that they can query it or export it separately
(`dj export set <id> --to bp_chart|bp_playlist|rekordbox`).

## How the engine works (for explaining / tuning)

### Intensity = a blend, not just loudness
The curve targets a **composite intensity** (1–10), pool-relative:

```
intensity = 10 · ( 0.60·norm(mik_nrg) + 0.25·pct(bpm) + 0.15·drive )
   drive = mean(drums_pct, bass_pct)      *_pct = percentile within the candidate pool
```

So "where are we in the night" uses MIK energy, tempo, and drum/bass drive
together — a slow loud record and a fast sparse one don't read as equal.

### The archetype curve (the strategy)
Each archetype is a list of `Phase` control points (`t`∈[0,1], target intensity
1–10, per-stem emphasis ∈[−1,+1]). Curves are **multi-phase and non-monotonic** —
e.g. `club_night` rises, bumps, **dips deliberately**, S-climbs, plateaus, dips
again, then spikes to a high finish. The walk interpolates the curve per step
(`_curve_at`) so the greedy target is always smooth. Stem emphasis pulls texture
into the arc: warm-ups lean melodic/vocal, peaks lean drum+bass, rotate-dips pull
a vocal breather. To reshape a night, edit the `Phase` points in
`ARCHETYPES[...]` — don't hand-tune per-track energies.

### Mixing guidelines (scored greedily; lower = better next track)

| Term | Weight | Meaning |
|---|---|---|
| intensity | ×2.0 | `\|track intensity − curve target\|` |
| bpm | ×1.0 | `\|bpm − prev.bpm\|` — smooth tempo |
| stem | ×1.5 | texture matches the phase emphasis |
| harmonic | method-graded | per-relationship penalty (see below); `mood` cheap, `fuzzy` expensive for bold moves |
| key repeat | `diversity·7` | candidate key seen in the last 3 tracks (anti-monotony) |
| fresh key | `−diversity·2` | candidate key not yet used anywhere in the set (reward) |
| vocal clash | +3 | both this and prev are vocal-led |
| same artist | +10 | back-to-back same artist |
| recent artist | +4 | artist used in the last 2 tracks |
| same label | +1.5 | back-to-back same label |

Hard constraints (skip, not penalise): **max 2 tracks per artist**; **recency
blend** (when no explicit date window); same-artist+title dedup.

### Harmonic methods (Camelot relationships)
`camelot_relationship(prev, cand)` classifies each move, then a per-method table
turns it into a penalty (`mood` tolerant, `fuzzy` strict):

| Relationship | Example (from 8A) | mood pen | fuzzy pen |
|---|---|---|---|
| match (same key) | 8A | 0.0 | 0.0 |
| scale (relative maj/min) | 8B | 0.3 | 0.4 |
| energy (±1 same letter) | 9A / 7A | 0.3 | 0.4 |
| boost (±2 same letter) | 10A / 6A | 0.7 | 1.2 |
| diagonal (±1 + letter switch) | 9B / 7B | 0.7 | 1.2 |
| mood (bold ±3..±5 jump) | 11A | 1.8 | 5.0 |
| clash (±6 tritone) | 2A | 6.0 | 9.0 |

So `fuzzy` keeps the sequence on safe moves (mixtape/radio); `mood` makes
energy-changing jumps cheap (live/party). **Diversity** then layers anti-monotony
on top so the walk rotates the wheel instead of repeating `match` forever — this
is what fixes "so many 1A / 2A in a row". Each archetype carries a suggested
`method` + `diversity`; `--method` / `--diversity` override per build and are
stored in `params_json`.

## Storage & edits (DB)

Sets persist in `dj_sets` / `dj_set_tracks` (`detect/db.py`). Identity is
`(name, type)` where **`type` is the archetype key**; rebuilding the same
name+archetype **replaces** it. Build provenance (mood, duration, count, genres,
date filter, curve) is stored as JSON in `dj_sets.params_json`, so a set is
self-describing.

```python
from detect import db
db.record_built_set(name, archetype, ids, params)  # what --save calls
db.get_set(set_id)                                  # header + params_json
db.tracks_in_set_id(set_id)                         # ordered rows by id (for export/query)
db.tracks_in_set(name, type)                        # ordered rows by name+archetype
db.add_track_to_set / remove_track_from_set / move_track_in_set / reorder_set
db.rename_set / delete_set / list_sets / sets_for_track / track_set_count
```

When the user says "add X to the set", "move track 5 to the top", "drop that
track", "what sets is this in", or "rename the set" → use these directly.

## Exporting (NOT this skill)

Building is decoupled from any destination. To push a stored set out, use the
separate command (planned): `dj export set <id> --to bp_chart | bp_playlist |
rekordbox`. Don't push to Beatport/rekordbox from this skill.

## Add or tune archetypes

- **New archetype** — add an entry to `ARCHETYPES` in `build_set.py` with default
  genres, a BPM/energy window, and a `Phase` curve. It appears in
  `--list-archetypes` automatically.
- **Reshape** — add/move `Phase` points (more back-third peaks = more
  rotate-the-floor pulses).
- **Retune intensity** — change `W_NRG / W_BPM / W_DRIVE` (sum to 1.0) or the
  scorer weights (`W_INTENSITY`, `W_BPM_SMOOTH`, `W_STEM`).
- **Tighter blends** — read `analysis_json` `energy.segments[]` and prefer a next
  track whose entry segment matches the current track's exit segment. Not in the
  default scorer (needs JSON parse); add as a term if blends feel abrupt.
