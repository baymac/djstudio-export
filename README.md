# dj

Unified DJ toolkit. Builds a fully-analysed track library: pull tracks in from Apple Music, Beatport, and detected audio sources, progressively enrich each track with Beatport metadata and DJ Studio analysis (key/energy/cues/stems). Then build energy-sequenced sets, and push any stored set or SQL-curated subset to a Beatport chart/playlist or a rekordbox playlist.

All tool-generated files live under `~/Music/dj/`:

![dj storage layout under ~/Music/dj/](docs/diagrams/storage-layout.svg)

<!-- Diagram source: docs/diagrams/storage-layout.d2 — edit that and re-run scripts/build-diagrams.sh -->



---

## Setup

```bash
uv sync
source .venv/bin/activate            # puts `dj` on your PATH
uv run playwright install chromium   # needed for SoundCloud browser fetch + helpers/download_course.py
```

Node.js (v18+) and npm are required for `dj vj cats start` and `dj course start`. Install via [nodejs.org](https://nodejs.org) or your package manager (`brew install node`). The first `start` run auto-installs npm dependencies.

Copy `.env.example` to `.env` and fill in credentials before using `detect` or `sync`.

Rekordbox must be **closed** before any rekordbox write (`dj export set <id> --to rekordbox`, `dj export rekordbox --query ...`).

DJ Studio must be **closed** before `dj enrich analyse`.

---

## Pipeline at a glance

![dj enrichment pipeline: sources → enriched_tracks → analysis](docs/diagrams/pipeline.svg)

<!-- Diagram source: docs/diagrams/pipeline.d2 — edit that and re-run scripts/build-diagrams.sh -->


Sync capture (`sync_tracks`/`sync_playlist_tracks`) is non-destructive — see the `dj sync` section. Pulling your existing Beatport playlists straight into `enriched_tracks` (the checkpoint) is done with `dj sync beatport pull`.

Each enrichment step is idempotent. `enriched_tracks_analysis` carries `dj_studio_at`; re-runs only pick up new work. You can stop at any point — every step is independently useful. A row exists in `enriched_tracks_analysis` only after `enrich analyse` has populated it; `enriched_tracks` carries everything Beatport-derived without any sibling rows in the analysis table. (A former rekordbox phrase round-trip was removed; the `rk_analysis_json` / `rekordbox_*_at` columns remain for old data but are no longer written.)

---

## Command tree

Every verb + its flags:

```
dj
├── sync                                                capture / restore / delete source-app playlists
│   │   Scope flags (same meaning for pull/push/delete): --playlists = user playlists only
│   │   (Apple: excl. Favourite Songs; Spotify: excl. Liked Songs); --library = the personal
│   │   collection (Apple: library + Favourite Songs; Spotify: Liked Songs); --all = both.
│   │   Beatport has only --all.
│   ├── music | spotify
│   │   ├── pull    [--playlists|--library|--all] [--playlist NAME] [--limit N] [--dry-run] [-v]   capture → dj.db (default --all)
│   │   ├── list                                        Captured playlists + ids
│   │   ├── push    [--playlists|--library|--all] [--readd-missing*] [--dry-run]   restore from dj.db (*music only)
│   │   │           |  --name NAME (--ids ID,… | --query SQL)                      ad-hoc selection → app playlist
│   │   └── delete  (--playlists | --library | --all) [--no-sync] [--yes] [--dry-run]   Delete from the APP (dj.db kept)
│   └── beatport                                        --all is the only scope (no library/liked concept)
│       ├── pull    [--all] [--playlist NAME] [--limit N] [--dry-run] [-v]   Beatport playlists → enriched_tracks
│       ├── list
│       ├── push    --all (restore every captured playlist)  |  --name NAME (--ids ID,… | --query SQL)
│       └── delete  --all [--no-sync] [--yes] [--dry-run]    Delete every Beatport playlist (enriched_tracks kept)
│
├── detect                                              detect tracks (Shazam audio + tracklist parsers)
│   ├── instagram      <url>  [-u USER] [-p PASS] [-o FILE] [--json] [--dry-run]
│   ├── radio-garden   <url>  [-i SEC] [-c SEC] [-d MIN] [--cooldown SEC] [--dry-run]
│   ├── mixcloud       <url>  [-u USER] [-p PASS] [-i SEC] [-c SEC] [-o FILE] [--json] [--dry-run]
│   ├── youtube        <url>  [-i SEC] [-c SEC] [-o FILE] [--json] [--dry-run]
│   ├── soundcloud     <url>  [-i SEC] [-c SEC] [-o FILE] [--json] [--dry-run]
│   ├── podbean        <url>  [-i SEC] [-c SEC] [-o FILE] [--json] [--dry-run]
│   ├── reddit         <url>  [--dry-run]                       (paste-into-vi tracklist parser)
│   ├── topdjmixes     <url>  [--dry-run]                       (paste-into-vi tracklist parser)
│   ├── 1001tracklists <url>  [--dry-run] [--paste] [--browser {brave,chrome,safari,firefox}]
│   ├── text           <name> [--url URL] [--dry-run]           Parse a pasted tracklist (no URL needed)
│   ├── spotify        <url|name>                               Import a Spotify playlist → detected_tracks
│   ├── gems           [--source {spotify,soundcloud,bandcamp,beatport}] [--genre G] [-n N] [--date {1mo,6mo,1yr,3yr}] [--no-save]
│   ├── fix-session    <id>   [--apply] [--threshold F]         Correct a session vs a confirmed tracklist (stdin)
│   └── <src>-delete-session <id> [--force]                     Delete a scan session + its tracks
│                                                               (reddit · topdjmixes · 1001tracklists · text · mixcloud · youtube · soundcloud · podbean · spotify)
│
├── enrich                                              build the enriched library
│   ├── (no subcommand) [--detect | --sync] [--dry-run] [--limit N] [--verbose] [--threshold F] [--retry-misses]
│   │                                                   Beatport metadata for detected + synced tracks (both by default)
│   └── analyse        [--ids ID,…] [--limit N] [--verbose] [--force] [--retry-failed]
│                                                       Drive DJ Studio's SDK → enriched_tracks_analysis
│
├── export                                              Push a stored set or SQL-curated subset to a destination
│   ├── set <id> --to {bp_chart|bp_playlist|rekordbox} [--name NAME] [--description TEXT] [--dry-run]
│   ├── beatport  --query SQL --name NAME [--dry-run]   Ad-hoc SQL (must SELECT beatport_id) → Beatport playlist
│   └── rekordbox --query SQL --name NAME [--dry-run]   Ad-hoc SQL (must SELECT beatport_id) → rekordbox playlist
│
├── course                                              Offline course viewer (apps/course)
│   ├── start                                           Spawn vite via portless, open https://course.localhost
│   └── stop                                            Kill the background process group
│
├── vj <name> start|stop                                Start/stop a VJ visualizer under vj/<name>/
│
└── extension pack <name>                               Zip a Chrome extension (apps/<name>-extension/) → ~/Music/dj/extensions/
```

---

## Beatport auth

`sync`, `enrich`, and `sync beatport` talk to Beatport. Auth is handled transparently by `connections/beatport.resolve_access_token`:

1. `BEATPORT_ACCESS_TOKEN` in `.env` (used if still valid)
2. `BEATPORT_SESSION_TOKEN` cookie in `.env` → refresh via Beatport's `/api/auth/session`
3. Browser cookie store (Brave by default, see `connections/cookies.py`) → same refresh

To bootstrap, sign into beatport.com in your default browser — every Beatport call refreshes the access token as needed and persists rotations back to `.env` (including a fresh `cf_clearance`). If Beatport returns `RefreshAccessTokenError`, sign out and back in on beatport.com to rotate the NextAuth session.

**Token lifetime:** `BEATPORT_ACCESS_TOKEN` expires in ~10 min. `BEATPORT_SESSION_TOKEN` lasts ~32 days. As long as the session token is valid, every command auto-refreshes the access token.

---

# Sync source-app libraries into the pipeline

Faithfully captures your Apple Music and Spotify playlists into the local DB, then enriches them against Beatport. Capture is **non-destructive**: tracks land in a canonical `sync_tracks` store (deduped per app by native id, else artist+title) and playlist membership is tracked separately in `sync_playlist_tracks`. Re-syncing a playlist re-snapshots only its membership — removed tracks lose their link but their captured data is never deleted, so a delete on the app's side can't wipe your backup. This mirrors the Beatport side (`enriched_tracks` + `beatport_playlist_tracks`).

```bash
# Pull (faithful capture, → sync_tracks + sync_playlist_tracks)
uv run dj_cli.py sync music pull                       # EVERYTHING (default --all): playlists + library + Favourite Songs
uv run dj_cli.py sync music pull --playlists           # only user playlists (excludes Favourite Songs)
uv run dj_cli.py sync music pull --library             # only library songs + Favourite Songs (incremental via cursor)
uv run dj_cli.py sync music pull --playlist "Ibiza 2026"  # only one named playlist
uv run dj_cli.py sync spotify pull                     # EVERYTHING (default --all): all playlists + Liked Songs (OAuth on first run)
uv run dj_cli.py sync spotify pull --library           # only Liked Songs
#   common flags: --limit N --dry-run --verbose

# Enrich captured tracks → enriched_tracks (`dj enrich metadata` covers both sources)
uv run dj_cli.py enrich metadata --sync
uv run dj_cli.py enrich metadata --sync --retry-misses

# Pull your Beatport playlists straight into enriched_tracks (checkpoint)
uv run dj_cli.py sync beatport pull

# Inspect / push captured playlists (every source supports pull | list | push | delete)
uv run dj_cli.py sync music   list
uv run dj_cli.py sync spotify push --name "Mirror" --query "SELECT t.* FROM sync_tracks t JOIN sync_playlist_tracks m ON m.sync_track_id=t.id WHERE m.app='spotify' AND m.native_playlist_id='<id>' ORDER BY m.position"
uv run dj_cli.py sync beatport push --name "Peak Tech" --query "SELECT beatport_id FROM enriched_tracks WHERE genre='Tech House'"   # beatport push selects by beatport_id (same engine as `dj export beatport`)

# Declutter the SOURCE APP — delete from Apple Music / Spotify / Beatport.
# Removes from the app only; your dj.db backup is ALWAYS kept. Offers to pull the
# latest first so the backup is current, then asks once before deleting.
uv run dj_cli.py sync music   delete --playlists   # delete all user playlists (Favourite Songs + library kept)
uv run dj_cli.py sync music   delete --library     # clear the library + Favourite Songs (playlists kept)
uv run dj_cli.py sync music   delete --all         # both
uv run dj_cli.py sync spotify delete --playlists   # unfollow all playlists (Liked Songs kept)
uv run dj_cli.py sync spotify delete --all         # the above + clears Liked Songs
uv run dj_cli.py sync beatport delete --all --yes  # every Beatport playlist, no prompts

# Restore the SOURCE APP from the dj.db backup. Inverse of delete (same scope flags).
uv run dj_cli.py sync music    push --playlists                 # recreate all playlists (matches in-library tracks)
uv run dj_cli.py sync music    push --library --readd-missing   # repopulate library + favorites; only re-add what's missing (resumable)
uv run dj_cli.py sync music    push --all --readd-missing       # playlists + library + favorites
uv run dj_cli.py sync spotify  push --playlists                 # recreate all playlists (adds tracks by id)
uv run dj_cli.py sync spotify  push --library                   # re-save Liked Songs
uv run dj_cli.py sync spotify  push --all                       # Liked Songs + all playlists
uv run dj_cli.py sync beatport push --all                       # recreate every Beatport playlist on the account
#   Apple Music catalog re-add (--library/--readd-missing) is best-effort via the
#   itmss:// trick — region-locked/removed tracks can't be re-added on macOS, and are skipped.
#   Spotify & Beatport restore are exact (the APIs add tracks by id; no re-add hack needed).
```

Spotify auth uses an Authorization-Code OAuth flow on first run (set `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`, redirect `http://127.0.0.1:8888/callback`); the refresh token is cached in `auth_cache`. Spotify's own algorithmic/editorial playlists (Discover Weekly, Release Radar, …) return 404 on their tracks endpoint and are skipped, not fatal. `dj sync music pull --library` tracks the last `library_added_date` in the `cursors` table so re-runs only capture new Apple Music additions. Logs: `~/Music/dj/logs/sync-spotify/` and `~/Music/dj/logs/sync-beatport/`.

---

# Detect tracks from audio sources

Identifies tracks playing in Instagram posts, radio streams, Mixcloud mixes, YouTube videos, SoundCloud mixes, and Podbean episodes via Shazam, or extracts them from Reddit / topdjmixes text posts via a paste-into-vi parser. Results land in `detected_tracks` (one row per unique track, deduped by Shazam key or artist + title). Re-scanning the same URL never creates duplicates.

Mixcloud, YouTube, SoundCloud, and Podbean scans auto-resume from where they left off if interrupted.

```bash
uv run dj_cli.py detect instagram https://www.instagram.com/p/XXXXX/

uv run dj_cli.py detect radio-garden https://radio.garden/listen/station-name
uv run dj_cli.py detect radio-garden <url> --interval 60    # check every 60s
uv run dj_cli.py detect radio-garden <url> --duration 120   # run for 2 hours

uv run dj_cli.py detect mixcloud https://www.mixcloud.com/djname/mixname/
uv run dj_cli.py detect youtube https://www.youtube.com/watch?v=XXXX
uv run dj_cli.py detect soundcloud https://soundcloud.com/dj/mix-name        # share-link tracking params auto-stripped
uv run dj_cli.py detect podbean https://www.podbean.com/ew/pb-XXXX
uv run dj_cli.py detect reddit https://www.reddit.com/r/HypeTracks/comments/XXXXX/post_title/
uv run dj_cli.py detect topdjmixes https://www.topdjmixes.com/some-mix-page/
```

**Credentials** (auth is automatic — no separate login command):
- Instagram: set `IG_USERNAME` / `IG_PASSWORD` in `.env`, or just run `dj detect instagram <url>` and enter them once when prompted; a successful login is saved and reused.
- Mixcloud: set `MC_USERNAME` / `MC_PASSWORD` (optional — public mixes work without). Freshly provided creds are saved and reused.
- SoundCloud: optional OAuth via `SOUNDCLOUD_CLIENT_ID` / `SOUNDCLOUD_CLIENT_SECRET` (register an app at https://soundcloud.com/you/apps). When configured, set/track metadata comes from SoundCloud's official API — clean artist/title fields, no rate-limit pain. When absent, falls back to yt-dlp scrape + URL-slug derivation (works but lower fidelity). Share-link tracking params (`?si=…`, `&utm_*=…`) are stripped automatically. The handler auto-detects three URL shapes:
    - **Set** (`/<user>/sets/<slug>`) → enumerate child tracks via metadata, no audio download.
    - **Single track ≤15 min** → save the track's metadata as one row (no Shazam scan).
    - **Single track >15 min** (radio episodes, DJ mixes) → Shazam-by-chunks audio scan.
    - SoundCloud auth is automatic from the client credentials above (token fetched + refreshed on demand). Personalized `/discover/` URLs need a user-bound OAuth token; that one-time browser OAuth helper (`connections.soundcloud.login_user`) is no longer wired to a CLI command — set `SOUNDCLOUD_REDIRECT_URI` and call it if you need personalized feeds.
- YouTube: no credentials needed. yt-dlp extracts cookies from the first available browser (Brave → Chrome → Safari → Firefox) and caches them for one week. If YouTube returns a bot-detection challenge, the cache is discarded and cookies are re-extracted before retrying. If no browser is available the fallback passes `--cookies-from-browser chrome` live.
- Reddit: none. Public JSON API. Works on any subreddit text post whose body contains `Artist - Title` lines (markdown links and `[brackets]` are stripped).
- topdjmixes: none. Paste-into-vi flow (same parser shape as Reddit). Works on any tracklist with `01. Artist – Title` lines — leading position numbers and `[label]` brackets are stripped.

### Sessions

The read-only browse commands (`history`, `sessions`, `*-history`, `enriched`,
`enrich-runs`, `enrich-tracks`) were removed — query the SQLite DB at
`~/Music/dj/dj.db` directly for inspection. Deleting a scan session is still a
command:

```bash
uv run dj_cli.py detect mixcloud-delete-session <id>
uv run dj_cli.py detect youtube-delete-session <id>
uv run dj_cli.py detect soundcloud-delete-session <id>
uv run dj_cli.py detect podbean-delete-session <id>
uv run dj_cli.py detect reddit-delete-session <id>
uv run dj_cli.py detect topdjmixes-delete-session <id>
```

### Correcting a session's detected tracks — `fix-session`

Shazam occasionally mis-identifies tracks. `fix-session` lets you paste a confirmed tracklist (from a set description, the DJ's own post, etc.) and remove any detected track that can't be matched to it.

```bash
# Dry-run — shows what would be removed (default):
uv run dj_cli.py detect fix-session 7

# Apply the removals:
uv run dj_cli.py detect fix-session 7 --apply

# Lower the match bar (default 0.75):
uv run dj_cli.py detect fix-session 7 --apply --threshold 0.6
```

Paste the confirmed tracklist into stdin (press Ctrl-D when done). Lines that match a detected track above `--threshold` are kept; the rest are removed from the session and deleted from `detected_tracks` if they haven't been enriched and aren't shared with another session. `--apply` is required to actually delete — without it the command prints the diff and exits.

---

# Discover hidden gems — `detect gems`

`detect gems` surfaces low-play / under-the-radar tracks in a genre, released within a chosen time window, across four platforms. It does **not** save finds automatically — instead it opens an interactive review where you listen to each track and decide. Approved tracks land in `detected_tracks` and flow straight into `dj enrich` and the rest of the pipeline.

Run it fully interactive (prompts for every choice) or pass flags — any omitted flag is prompted for:

```bash
uv run dj_cli.py detect gems                                                          # fully interactive
uv run dj_cli.py detect gems --source beatport --genre "Tech House" --count 10 --date 1mo
uv run dj_cli.py detect gems --source soundcloud --count 15 --date 6mo
uv run dj_cli.py detect gems --source bandcamp --count 5 --date 6mo --no-save          # show only, skip review
```

| Flag | Values | Description |
|---|---|---|
| `--source` | `spotify` / `soundcloud` / `bandcamp` / `beatport` | Platform to search |
| `--genre` | `Tech House` | Genre (only Tech House is mapped today) |
| `--count` / `-n` | 1–20 | Number of **new** tracks to return |
| `--date` | `1mo` / `6mo` / `1yr` / `3yr` | Max track age (release window) |
| `--no-save` | — | Show the results table and skip the review step entirely (testing) |

**Per-source "gem" signal** — each platform exposes different data, so the genre filter and the low-play proxy differ:

| Source | Genre filter | Low-play proxy | Notes |
|---|---|---|---|
| **Beatport** | exact `genre_id` (real taxonomy) | excludes Hype (label-paid promotion) tracks | most genre-accurate; result table shows BPM + Camelot key; Beatport has no public play count |
| **SoundCloud** | `genres=` tag search | `playback_count < 5000` | real play counts via the public API |
| **Spotify** | editorial-playlist mining | `popularity ≤ 25` (widens to 35 if sparse) | Spotify's `genre:` search filter is unreliable for sub-genres, so it mines genre playlists for low-popularity tracks |
| **Bandcamp** | `tag_norm_names` via `discover/1/discover_web` | none — Bandcamp exposes no play count | tags are uploader-applied free text, so genre accuracy is approximate |

For strict genre accuracy, prefer **Beatport** — it is the only source with an authoritative genre taxonomy. Bandcamp tags in particular are uploader-supplied and noisy.

**Review.** After a scan, gems are not saved — `detect gems` walks the finds one at a time, printing each track's link so you can open it and listen, then prompts for a decision:

- **approve** (`a`) — the track is saved to `detected_tracks` and enters the pipeline.
- **reject** (`r`) — the track is recorded in `rejected_gems` and never enters the pipeline; it won't surface again in future scans.
- **skip** (`s`, the default) — the track is left undecided and not persisted anywhere, so it can reappear in a later scan.
- **quit** (`q`) — stop reviewing; the remaining tracks are left undecided.

**Persistence and cross-run dedup.** Approving at least one track records a `sessions` row (`type='gems'`) plus a `gem_scans` row (source, genre, requested/found counts, date window) and one `gem_tracks` row per approved track (url, release date, plays/popularity); approved tracks land in `detected_tracks` through the normal dedup path. Rejected tracks go to `rejected_gems` instead. The **next** run on the same platform skips every track it already approved *or* rejected and keeps paging until it has `--count` genuinely-new tracks — there is no fixed page offset, so it works even as a platform's results reshuffle over time. Prior gems (approved or rejected) whose release date is older than the current `--date` window are "faded" out of the comparison set (they cannot recur in a narrower window anyway), keeping the dedup check cheap. `--no-save` skips review and all persistence — results display but nothing is written, and the dedup history is left untouched.

**Credentials:**
- Spotify: `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` in `.env` (create an app at https://developer.spotify.com/dashboard). Prompted for interactively if missing.
- SoundCloud: `SOUNDCLOUD_CLIENT_ID` / `SOUNDCLOUD_CLIENT_SECRET` — the same credentials `detect` uses.
- Beatport: the usual `BEATPORT_ACCESS_TOKEN` / `BEATPORT_SESSION_TOKEN` (same as `sync`, `enrich`, and `sync beatport`).
- Bandcamp: none — public discover API.

---

# Enrich detected tracks with Beatport metadata

Takes everything in `detected_tracks` that doesn't have a Beatport match yet, fuzzy-matches each one against Beatport search, and pulls full track metadata. Tracks with no result or score below threshold are marked on `detected_tracks.enrich_outcome` (`not_found` or `fuzzy_miss`) and skipped on future runs.

Each match writes one row to `enriched_tracks` carrying every Beatport-derived field on the same row: the basic search-result fields (`bpm`, `key`, `genre`, `release_date`, `beatport_id`, `beatport_link`, `artist`, `title`, `apple_music_url`) plus the catalog-detail extras (`mix_name`, `label`, `catalog_number`, `isrc`, `sub_genre`, `length_ms`) fetched from `/v4/catalog/tracks/{id}/`.

Beatport-sourced data is fetched **only** here (and inline-extracted by `sync beatport` from the playlist response). `enrich analyse` does not call Beatport.

`dj enrich metadata` enriches both detected and synced tracks by default; scope it with `--detect` or `--sync`.

```bash
uv run dj_cli.py enrich metadata                      # enrich detected + synced tracks
uv run dj_cli.py enrich metadata --detect             # only detected tracks
uv run dj_cli.py enrich metadata --detect --dry-run
uv run dj_cli.py enrich metadata --detect --limit 50
uv run dj_cli.py enrich metadata --detect --verbose            # print per-track Beatport detail
uv run dj_cli.py enrich metadata --detect --threshold 0.8      # stricter match (default: 0.72)
uv run dj_cli.py enrich metadata --detect --retry-misses       # retry previously missed tracks
```

Log written to `~/Music/dj/logs/enrich/YYYY-MM-DD_<run_id>.log`. Every other command writes to `~/Music/dj/logs/<command>/YYYY-MM-DD_<HHMMSS>.log` automatically.

---

# Pull Beatport library tracks directly

For tracks already in your Beatport library (bought, favourited, in playlists), there is no detection step — just sync them straight into `enriched_tracks`. The catalog-detail extras (`mix_name`/`label`/`isrc`/`sub_genre`/`length_ms`) are pulled inline from the same playlist response so no extra HTTP call per track is needed.

```bash
uv run dj_cli.py sync beatport pull
uv run dj_cli.py sync beatport pull --dry-run
uv run dj_cli.py sync beatport pull --limit 100
uv run dj_cli.py sync beatport pull --verbose
```

`enrich metadata --detect` and `sync beatport pull` produce identical-shaped rows in `enriched_tracks`. Analysis doesn't care which path a row came from.

---

# DJ Studio analysis (key, energy, cues, beatgrid, stems)

One command: **`dj enrich analyse`** drives DJ Studio's bundled SDK headlessly and writes results directly into `enriched_tracks_analysis`. **Doesn't touch DJ Studio's filesystem at all** — DJ Studio's `audio-library-table` / `track-structures-table` / `compressedAudioView*` binaries are never written to.

### enrich analyse — drive DJ Studio's analysis headlessly

Uses your DJ Studio account + the bundled SDK to fetch full Beatport tracks, run the same MIK + ai-beatgrid + ai-stems pipeline DJ Studio uses internally, and write rows directly into `enriched_tracks_analysis` — no UI interaction, no DJ Studio filesystem pollution.

**Per track captured (in our DB):**

| Source | Output |
|---|---|
| `cf.dj.studio/mixedinkey/analyze` (via WASM features) | `mik_key`, `mik_key_secondary`, `mik_key_confidence`, `mik_nrg` (1-10), full energy segments + cue points (in `analysis_json`) |
| `@appmachine/ai-beatgrid` (TorchScript) | `tempo_precise` (full-precision BPM), all beat positions, downbeat (in `analysis_json`) |
| `@appmachine/ai-stems` Demucs Fast | per-stem `*_avg` / `*_peak` RMS floats; in `analysis_json`, `stems[stem].curve_1hz` (1Hz time-series) + `stems[stem].per_segment` (avg/peak per energy segment) |

(Beatport metadata — mix_name, label, catalog_number, ISRC, sub_genre, length_ms — was already fetched during enrich and is on `enriched_tracks`.)

**Prerequisites:**
1. **Quit DJ Studio (Cmd+Q)** before running. Its SDK conflicts with ours on port 61894 + `.beatport/` cache locks. Pre-flight check aborts with a clear message if DJ Studio is running.
2. Sign into DJ Studio + Beatport via the UI at least once. Demucs model weights (`~/Library/Application Support/DJ.Studio/extensions/djs-stems/models/htdemucs_fast_encrypted.pt`) must be downloaded — DJ Studio prompts on first launch. We share these weights; we don't run our own Demucs.
3. DJ Studio refresh token must be valid. If expired, open DJ Studio briefly to refresh, quit it, re-run.

**`cf.dj.studio`** is DJ Studio's Cloudflare-hosted classification API. The local WASM extracts pitch/energy features; the server classifies them into a Camelot key + 1-10 energy + segment boundaries + cue points. Same flow the desktop app uses internally — verified bit-identical output for `mik_key`/`mik_nrg`/`bpm`/`duration`/`beat_count` against tracks DJ Studio analysed via its UI. (DJ Studio applies some display-time post-processing — rounded BPM, segment merging, cue trimming, BP-key override of mikKey — that we deliberately skip to keep the fuller raw signal.)

This command runs `caffeinate -i` automatically — your Mac won't sleep mid-run. Same applies to `dj enrich metadata` (sequential Beatport API calls) and `detect radio-garden` (indefinite monitoring loop).

```bash
# Small sanity-check batch
uv run dj_cli.py enrich analyse --limit 5 --verbose

# Full batch
uv run dj_cli.py enrich analyse --verbose

# Re-process specific tracks (e.g. after fixing a bug in _shape_result)
uv run dj_cli.py enrich analyse --ids 23330162,21531599 --force --verbose
```

**Flags:**
- `--ids ID,ID,...`: only analyse these beatport IDs. Bypasses `--limit` and the short-track / failure-sidecar filters; still respects the dedupe filter unless paired with `--force`.
- `--limit N`: stop after N tracks (0 = no limit). Ignored when `--ids` is set.
- `--force`: re-process tracks even if a row already exists in `enriched_tracks_analysis`.
- `--retry-failed`: ignore the hard-failure sidecar and re-attempt tracks that previously hit the failure cap.

**Idempotent:** skip rule is "row exists in `enriched_tracks_analysis` for this beatport_id". Re-runs only process new tracks.

**JWT auto-refresh mid-run:** DJ Studio's access JWT lasts ~60 min. On the first 401 from `cf.dj.studio` the run re-decrypts `encryptedToken-v2.dat`, re-exchanges via `app-services.dj.studio`, pushes the fresh token down to the running Node helper (`setAccessJwt` command — no helper restart, no model reload), and retries the failed track. Long batches don't need babysitting. If the post-refresh retry also 401s, the run aborts with a clear message — that means `encryptedToken-v2.dat` itself is invalid (open DJ Studio, sign in, quit, re-run).

**Failure handling:** transient `cf.dj.studio` failures are auto-retried inside the Node helper (4 attempts, exponential backoff up to 9s). Tracks that still fail get a second pass at the end of the batch after a 5s pause. Tracks that fail on both first pass and retry are recorded in a sidecar (`~/Music/dj/state/studio_analyse_failures.json`) and auto-skipped on subsequent runs once they hit `MAX_FAILURE_ATTEMPTS` (3) — bypass with `--retry-failed`. The summary distinguishes "written / recovered on retry / permanently failed" with per-track error reasons.

**Per-track timing:** ~30-50s per track on first run (SDK + model cold-start), ~25-30s steady-state. ~2GB peak memory (Demucs models). 100 tracks ≈ 50-60 minutes.

### Stored in `enriched_tracks_analysis` after `enrich analyse`

```
beatport_id              -- PRIMARY KEY (link to enriched_tracks via JOIN)
mik_key, mik_nrg         -- from cf.dj.studio classifier
mik_key_secondary        -- secondary key candidate
mik_key_confidence       -- 0-1 confidence on main key
tempo_precise            -- full-precision BPM (DJ Studio rounds; we don't)
duration_sec             -- track duration
cue_points_count         -- count from classifier
vocals_avg, drums_avg, bass_avg, melody_avg     -- per-stem aggregate RMS
vocals_peak, drums_peak, bass_peak, melody_peak -- per-stem peak RMS
analysis_json            -- compact JSON blob: full energy segments,
                            cue points, tempo, structure, stems with
                            curve_1hz (~300 floats per stem) +
                            per_segment (avg/peak per energy segment)
dj_studio_at             -- set on first INSERT
```

**Not stored** (intentionally): semantic phrase labels (intro/chorus/breakdown/etc.). DJ Studio doesn't produce those — its renderer never calls the dormant ML phrase model and real `track-structures-table.phraseData` arrays are empty.

> **Removed — rekordbox phrase round-trip:** an earlier flow pushed tracks to rekordbox (`detect export-to-rekordbox`), had you run rekordbox's *Analyze Tracks*, then read PSSI phrase tags + cues back into `rk_analysis_json` (`detect import-rekordbox-analysis`). Both commands are gone. The `rk_analysis_json` / `rekordbox_export_at` / `rekordbox_analysis_at` columns remain for pre-existing data but are no longer written, and the library currently carries no semantic phrase labels. To send a curated set to rekordbox, use `dj export set <id> --to rekordbox`.

Inspecting enriched data: the read-only browse commands (`detect enriched`, `enrich-runs`, `enrich-tracks`, `history`, `sessions`) were removed — query `~/Music/dj/dj.db` directly.

---

## Building a set — `dj-set-builder` skill + `helpers/build_set.py`

A set is curated as an **intensity curve over time**, not a flat genre filter. Pick an *archetype* (a named energy shape), and the engine walks the analysed library choosing each next track so the set follows that shape while staying mixable (harmonic + tempo + texture) and varied (familiar names interleaved with gems). The result is stored in `dj_sets` and addressed by a returned **set id**. Building does **not** export — that's the separate `dj export set <id>` step.

The `dj-set-builder` skill is the interactive front end: it asks for a name, mood/occasion, duration, track count, genres, and release-date mix, then runs `build_set.py` with the resolved flags. You can also drive the script directly.

```bash
uv run helpers/build_set.py --list-archetypes              # catalogue + each one's default genres + curve
uv run helpers/build_set.py --list-genres --archetype party   # library genres + live track counts (* = default)

# Preview (no DB write):
uv run helpers/build_set.py --archetype club_night --duration 120

# Build + store (prints set_id=<n>):
uv run helpers/build_set.py --archetype party --name "Maya's Bday" --mood "friends birthday" \
  --duration 90 --count 24 --genres "House,Tech House,Bass House" \
  --date-blend '[{"label":"this year","from":"2026-01-01","ratio":0.9},{"label":"older","to":"2025-12-31","ratio":0.1}]' \
  --save
```

**Archetypes** (extend `ARCHETYPES` in `build_set.py` to add more): `warmup`, `peak_time`, `late_night`, `closing`, `club_night`, `sunset`, `party`, `dark`, `festival`, `dinner`, `morning_coffee`. Each carries default genres, a BPM/energy window, and a multi-phase **non-monotonic** curve — e.g. `club_night` rises, bumps, dips deliberately, S-climbs to a plateau, dips again, then spikes to a high finish.

**Composite intensity** — the curve targets a pool-relative blend, not raw loudness:

```
intensity = 10 · ( 0.60·norm(mik_nrg) + 0.25·pct(bpm) + 0.15·drive )    drive = mean(drums_pct, bass_pct)
```

so a slow loud record and a fast sparse one don't read as equal energy. The greedy scorer also rewards Camelot-adjacent keys + smooth BPM + stem-texture matching the phase (warm-ups pull melodic/vocal, peaks pull drum+bass), and spaces artists/labels (max 2 tracks per artist).

**Flags:**
- `--archetype` (required), `--duration` minutes (required). Track count is clamped to `[duration/5, duration/2]`; `--count` sets it, default `≈duration/3.5`.
- `--genres "A,B,C"` overrides the archetype defaults (your choice is final); omit to use defaults.
- `--date-blend '<json>'` — proportional release-date mix: a list of `{label, from, to, ratio}` buckets, filled to ~each ratio (a single window is one 100% bucket). Omit for the default 75% ≤1yr / 12.5% 1–2yr / 12.5% older mix. The skill converts free text ("may 2026 50%, jan 30%, feb 20%") into this JSON.
- `--seed-id <beatport_id>` forces a track first; `--json` emits the built set; `--save` persists and prints `set_id=`.

Sets persist in `dj_sets` / `dj_set_tracks`: identity is `(name, archetype)`, so rebuilding the same name+archetype **replaces** it, and the full build provenance (mood, duration, count, genres, date blend, curve) is stored as JSON in `dj_sets.params_json`. Query a stored set by id, or edit it (add/remove/move/reorder/rename) via the helpers in `detect/db.py`.

---

## export — stored set or SQL query → Beatport / rekordbox

The set builder (the `dj-set-builder` skill, or `helpers/build_set.py`) curates and sequences a set, stores it in `dj_sets`, and hands back a **set id**. It does not export. `dj export set <id>` is the separate, decoupled step that pushes a stored set's tracks — **in set order** — to a destination.

```bash
uv run dj_cli.py export set 42 --to bp_chart                        # publishable Beatport chart (draft)
uv run dj_cli.py export set 42 --to bp_playlist --name "Peak Time"  # Beatport playlist
uv run dj_cli.py export set 42 --to rekordbox --dry-run             # rekordbox playlist (quit rekordbox first)
```

- `--name` overrides the destination chart/playlist name (defaults to the set's stored name).
- `--description` applies to `bp_chart` only; without it the description is built from the set's stored mood / duration / archetype.
- `bp_chart` creates an **unpublished draft** — publish it from beatport.com → DJ profile → Charts. Insertion order becomes chart position, so tracks land in set order.
- `rekordbox` re-fetches full rows (artist/title/genre/key/bpm/duration) before pushing; quit rekordbox first, then Analyze Tracks in rekordbox to generate beatgrid + cues.
- All destinations accept `--dry-run`.

### Ad-hoc SQL → destination

For a one-off push without building a stored set, give a SQL query that returns
`beatport_id` (the former `dj playlist` command):

```bash
uv run dj_cli.py export beatport \
  --query "SELECT beatport_id FROM enriched_tracks WHERE genre='Tech House' AND bpm BETWEEN 124 AND 128 ORDER BY bpm" \
  --name "Peak Tech House"

# Filter on analysis-table columns by JOINing yourself; quit rekordbox first:
uv run dj_cli.py export rekordbox \
  --query "SELECT e.beatport_id FROM enriched_tracks e JOIN enriched_tracks_analysis a USING(beatport_id) WHERE a.mik_nrg>=7 LIMIT 30" \
  --name "High-energy set"
```

The query must start with `SELECT`; if no `beatport_id` is in the result set the
call errors. After fetch, each row is re-fetched via `enriched_tracks LEFT JOIN
enriched_tracks_analysis USING(beatport_id)` so push code always has
artist/title/genre/key/bpm/length_ms. Both verbs accept `--dry-run`.

The push code lives in `export/to_beatport.py` + `export/to_rekordbox.py` —
one home for "write tracks to a destination", shared by all three `dj export` verbs.

---

## Environment variables

Copy `.env.example` to `.env` and set these before using `detect` or `sync`.

```
BEATPORT_ACCESS_TOKEN    Short-lived Bearer token (~10 min). Auto-refreshed via session token.
BEATPORT_SESSION_TOKEN   Long-lived NextAuth session cookie (~32 days). Used to refresh access token.

IG_USERNAME              Instagram username (for detect instagram)
IG_PASSWORD              Instagram password

MC_USERNAME              Mixcloud username (for detect mixcloud)
MC_PASSWORD              Mixcloud password

SPOTIFY_CLIENT_ID        Spotify app client ID (for detect gems --source spotify)
SPOTIFY_CLIENT_SECRET    Spotify app client secret

SOUNDCLOUD_CLIENT_ID     SoundCloud app client ID (for detect soundcloud + detect gems)
SOUNDCLOUD_CLIENT_SECRET SoundCloud app client secret
SOUNDCLOUD_REDIRECT_URI  OAuth callback URL (only for the optional user-OAuth helper)
```

Beatport auth runs from your default browser's cookie store — no env vars to set. Just sign into beatport.com once. If you need to seed the tokens manually:
1. Open `beatport.com` in a browser (logged in)
2. DevTools → Network → find `/api/auth/session` → response JSON → copy `token.accessToken` → `BEATPORT_ACCESS_TOKEN`
3. DevTools → Application → Cookies → copy `__Secure-next-auth.session-token` (~3 KB value) → `BEATPORT_SESSION_TOKEN`

---

## Database schema

All tables live in `~/Music/dj/dj.db`.

| Table | Written by | Contents |
|---|---|---|
| `detected_tracks` | `detect` | One row per unique track. `enrich_outcome` records miss state (`not_found`, `fuzzy_miss`). Deduped by Shazam key or artist+title. |
| `sessions` | `detect` | One row per unique URL scanned (youtube, mixcloud, soundcloud, radio, instagram, podbean, reddit, topdjmixes). Tracks scan progress and resume position. |
| `track_sessions` | `detect` | Junction: maps each track to the session(s) it appeared in, with timestamp position. |
| `gem_scans` | `detect gems` | One row per gems run: source, genre, requested/found counts, date window, linked `sessions` row. |
| `gem_tracks` | `detect gems` | Per-track gems metadata (url, release_date, plays, popularity) linking a `detected_tracks` row to a `gem_scans` row. Indexed on `(source, release_date)` for the cross-run dedup "fade" query. |
| `rejected_gems` | `detect gems` | Tracks the user rejected during gem review (source, artist, title, url, release_date). Excluded from future scans on that source. Indexed on `(source, release_date)` for the cross-run dedup "fade" query. |
| `enriched_tracks` | `enrich --detect`, `sync beatport` | All Beatport-derived data on one row: id, detected_track_id, beatport_id, beatport_link, bpm, key, genre, release_date, artist, title, apple_music_url, enriched_at, plus the catalog-detail extras (mix_name, label, catalog_number, isrc, sub_genre, length_ms). |
| `enriched_tracks_analysis` | `enrich analyse` creates rows | Sparse — only tracks that have been through `enrich analyse`. Keyed on `beatport_id` (PK). Carries the DJ Studio analysis fields (mik_key, mik_nrg, mik_key_secondary, mik_key_confidence, tempo_precise, duration_sec, cue_points_count, vocals/drums/bass/melody {avg,peak}, analysis_json with full energy segments + 1Hz stem curves + per-segment stem RMS) + `dj_studio_at`. The `rk_analysis_json` / `rekordbox_export_at` / `rekordbox_analysis_at` columns survive from the removed rekordbox round-trip but are no longer written. JOIN with `enriched_tracks` for the basic+catalog fields. |
| `enrich_runs` | `enrich metadata --detect` | Per-run summary: seen / found / not_found / fuzzy_miss / status. |
| `deleted_sessions` | `detect *-delete-session` | Audit log of deleted sessions. |
| `sync_tracks` | `sync music`/`sync spotify` | Canonical captured tracks, one row per `(app, dedup_key)` (native id, else artist+title). Append-only/upsert — never deleted by a re-sync. Carries `enrich_outcome` / `enriched_beatport_id` once per unique track. |
| `sync_playlist_tracks` | `sync music`/`sync spotify` | Playlist membership: `(app, native_playlist_id, playlist_name, sync_track_id, position)`. Re-snapshotted per playlist sync; a removed track loses its link but keeps its `sync_tracks` row. |
| `auth_cache` | `sync` | Per-service refresh-token cache (e.g. Spotify): service, token, captured_at, expires_at. |
| `cursors` | `sync` | Apple Music library incremental sync cursor (last `library_added_date` processed). |

---

## Helpers

```bash
# Rekordbox playlist cleanup — wipe a playlist + its tracks + cues
uv run helpers/cleanup_playlist.py --list
uv run helpers/cleanup_playlist.py "Ibiza Vibes" --dry-run
uv run helpers/cleanup_playlist.py "Ibiza Vibes"
uv run helpers/cleanup_playlist.py "Ibiza Vibes" --delete-tracks

# Apple Music backup / restore
uv run helpers/backup_apple_music.py
uv run helpers/backup_apple_music.py --output ~/backup.json
uv run helpers/restore_apple_music.py --backup ~/backup.json --dry-run
uv run helpers/restore_apple_music.py --backup ~/backup.json

# Apple Music library tools
uv run helpers/export_apple_music.py         # CSV export
uv run helpers/clear_apple_music.py --dry-run
uv run helpers/clear_apple_music.py          # DESTRUCTIVE — clears library

# Delete a single track from a Beatport playlist
uv run helpers/delete_beatport_track.py \
  --track https://www.beatport.com/track/title/12345678 \
  --playlist "Tech House"
```

---

## Course viewer

Download and watch the Pete Tong DJ Academy / Circle course offline.
All course data lives under `~/Music/dj/course/` (or an SSD — see below).

### Downloader

#### `login`

```bash
uv run helpers/download_course.py login <course_url>
```

Opens a headed (visible) browser window. Sign in manually. The session is saved
to a persistent browser profile at `~/Music/dj/state/course-browser-profile/`
and reused by every subsequent `download` run — you only need to `login` once (or
after your session expires).

#### `download`

```bash
uv run helpers/download_course.py download <course_url> [flags]
```

Resumes from where it left off. For each lesson in course order it: navigates,
classifies the page type, extracts content (video, quiz, HTML, attachments),
clicks "Complete lesson" to unlock the next, and writes the manifest after each
lesson so progress survives interruption.

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--out-dir PATH` | `~/Music/dj/course/` | Write all output (videos, manifest, quizzes, etc.) to a custom directory instead of the default. Use this to download a second course without clobbering the first. |
| `--limit N` | all | Stop after processing N lessons. The full manifest is still written for all discovered lessons; only the first N are actively scraped. Useful for smoke-testing after a code change. |
| `--dry-run` | off | Discover and print all lessons (title, ID, type, status) without downloading anything. No browser navigation, no file writes. |
| `--lesson-ids ID1,ID2,...` | all | Re-scrape only the listed lesson IDs, bypassing the normal "already complete" skip. Implies `force=True` for those lessons — quizzes are re-brute-forced from scratch even if `quizzes/<id>.json` already exists. Use after fixing a scraper bug, recovering a failed video, or re-running timed-out quizzes. |

**Skip logic** — a lesson is skipped (cached) unless `--lesson-ids` targets it:
- `extracted=True` AND `completed=True` AND video file present (or lesson has no video) → skip
- Otherwise → process

**Lesson types extracted:**

| Type | Description |
|------|-------------|
| `video_circle` | Circle-native HLS video: m3u8 captured via network sniffer, segments downloaded, muxed to mp4 |
| `video_dyntube` | Dyntube iframe video: AES-128 HLS key captured, manifest rewritten to local key URI, then downloaded |
| `quiz` | Multiple-choice quiz: brute-forced to find correct answers, saved to `quizzes/<id>.json` |
| `exercise` | Written exercise / assignment — HTML prose only, no video |
| `guide` | Reference / guide page — HTML prose only |
| `content` | Generic content page — HTML prose only |
| `locked` | Not yet unlocked on the platform (prior lesson incomplete) |
| `unknown` | Scraper couldn't classify the page (usually means it wasn't reached) |

**Common re-scrape recipes:**

```bash
# Re-run a single failed quiz
uv run helpers/download_course.py download <course_url> --lesson-ids 2569067

# Re-run several timed-out quizzes at once
uv run helpers/download_course.py download <course_url> --lesson-ids 2503039,2556782,2562957,2569067

# Re-scrape unknown/unextracted lessons
uv run helpers/download_course.py download <course_url> --lesson-ids 2623038,943070,943071

# Test the first 5 lessons only
uv run helpers/download_course.py download <course_url> --limit 5 --dry-run
```

**Output layout** under `~/Music/dj/course/`:

```
lessons.json        full manifest — one entry per lesson
videos/             downloaded mp4 files
images/             lesson images
files/              lesson file attachments
quizzes/            quiz JSON (one file per quiz lesson)
thumbs/             video poster frames
subtitles/          VTT subtitle files
_keys/              captured AES-128 keys for Dyntube HLS videos
_hls/               rewritten m3u8 manifests (local key URIs)
failed.json         lessons that errored or timed out during the last run
```

Logs are written automatically to `~/Music/dj/logs/download-course/YYYY-MM-DD_HHMMSS.log`.
The run holds a `caffeinate -i` power assertion so the Mac won't sleep mid-download.

### Viewer — `dj course start` / `dj course stop`

```bash
dj course start      # first run: npm install runs automatically (~30s)
                     # opens https://course.localhost:1355 in your default browser
dj course stop       # kill the background server
```

The viewer is at `apps/course/` (a Vite + React app). `dj course start` spawns
`npx portless course npm run dev` in the background, saves the PID at
`~/Music/dj/state/course.pid`, and opens the URL portless picked. Running
`start` again while the server is up just reopens the URL.

Vite serves everything from `~/Music/dj/` as static assets (one directory per
course, e.g. `dj-academy/`, `producer-academy/`). No backend, no network requests
during playback. Video position and lesson completion state are saved to
`localStorage`. If one course's directory is missing (e.g. a symlink to an
unmounted drive) the viewer logs the failure and falls through to the next
available course rather than crashing.

#### Logs

- Server stdout / vite output: `~/Music/dj/logs/course/YYYYMMDD_HHMMSS.log`
- Resolved URL (parsed from the portless log): `~/Music/dj/state/course_url.txt`
- PID: `~/Music/dj/state/course.pid`

#### Optional one-time setup (port-free URL)

By default the URL has a port number (`https://course.localhost:1355`) because
the portless proxy can't bind port 443 without root. Two commands fix that:

```bash
npx portless service install     # launchd daemon on port 443 (sudo prompt)
npx portless trust               # add portless's local CA to the system trust store
```

After both, the URL drops to `https://course.localhost` and browsers stop
warning about self-signed certs. Neither is required — the viewer works fine
with the port in the URL.

`service install` only auto-starts the **proxy** on boot, not the viewer. You
still need to run `dj course start` once per session to launch vite.

### Moving course files to an external SSD

The course directory is ~30 GB. To move it off the boot drive:

```bash
# 1. Move the files to the SSD (substitute your actual mount point)
mv ~/Music/dj/course /Volumes/YourSSD/dj-course

# 2. Symlink the original path to the new location
ln -s /Volumes/YourSSD/dj-course ~/Music/dj/course
```

The symlink is transparent to Vite, the downloader, and `paths.py` — nothing else needs
to change. Make sure the SSD is mounted before starting the viewer or running the
downloader.

---

## 1001tracklists PiP — Chrome extension

PiP a DJ mix and see the tracklist while continuing your work. A Chrome MV3
extension at `apps/1001T-extension/` that opens a YouTube DJ mix in a floating
Document Picture-in-Picture window with the full tracklist from
1001tracklists.com overlaid inside it. The current track highlights as the mix
plays, so the video and the IDs stay on top of whatever else you're doing.

![1001T PiP window with tracklist overlay](apps/1001T-extension/screenshot.png)

**Flow:**

1. Open any tracklist page on `1001tracklists.com/tracklist/…`
2. A red **"Open PiP + Tracklist"** button appears top-right — click it
3. The matching YouTube video opens in a new tab; a second red button appears there
4. Click that second button → the floating PiP window appears with video + scrollable tracklist
5. As the mix plays, the active track highlights and the list auto-scrolls

The last 20 tracklists are cached locally, so revisiting a YouTube video without
going through 1001TL still shows the button. Keyboard shortcut `Cmd+Shift+P` /
`Ctrl+Shift+P` opens PiP from whichever tab (1001TL or YouTube) is active.

**Install (unpacked):**

```bash
# 1. Open chrome://extensions (or brave://extensions)
# 2. Enable "Developer mode" (top-right toggle)
# 3. Click "Load unpacked" and pick:
#    apps/1001T-extension/extension/
```

No toolbar button — the extension works purely via the injected floating buttons
on 1001TL and YouTube pages.

**End-to-end QA** (headed Chromium via Playwright):

```bash
cd apps/1001T-extension
npm install
node qa-test.js          # screenshots → qa-screenshots/
```

See `apps/1001T-extension/README.md` for the full file layout and dev notes.

---

## VJ visualizer — `vj/cats/`

An audio-reactive browser visualizer built around a DJ's cats — procedural cat
poses in WebGL, real cat photos that dance to the music, and cinematic AI videos
that ping-pong loop. Vite + p5.js + Meyda + aubio.js, runs entirely in the
browser, no backend.

```bash
dj vj cats start            # first run: `npm install` runs automatically (~30s)
                            # opens https://cats.localhost
dj vj cats stop             # kill the background process group
```

Tap **TAP TO START**, grant mic permission, play music — the show cycles
through four sections forever (intro → procedural cat dots → photo cats →
cinematic catwoman videos). Keys: `F` fullscreen, `D` debug HUD, `N`/`M` skip
section/scene, `R` rotate canvas.

Local-only — there's no hosted deploy. The command auto-discovers any
`vj/<name>/` subdirectory with a `package.json` that has a `dev` script, so
adding a new VJ app is just `mkdir vj/whatever && cd vj/whatever && npm init`;
`dj vj whatever start` will work the next time you run it (no code change in
the CLI needed). See `vj/cats/README.md` for the asset recipes, audio routing
setup (BlackHole / VB-Audio Cable), and the full scene mod guide.

---

## Tests

```bash
uv run pytest
```

---

## Package layout

![dj package layout](docs/diagrams/package-layout.svg)

<!-- Diagram source: docs/diagrams/package-layout.d2 — edit that and re-run scripts/build-diagrams.sh -->


---

## Blog

- [How dj detect enrich works](https://www.baymac.lol/posts/dj-detect-enrich) — deep-dive into the Beatport fuzzy-matching + enrichment pipeline (detect + enrich)

## Credits

**Built by [baymac](https://github.com/baymac) for JAKE FURY**

- SoundCloud — https://soundcloud.com/jake_fk
- Mixcloud — https://www.mixcloud.com/jake_fk/
- Instagram — https://www.instagram.com/jakefury.dj/

The VJ visualizer at `vj/cats/` features **Mewtwo** (orange) and **Chewtwo**
(grey), and is built with [p5.js](https://p5js.org), [Meyda](https://meyda.js.org),
[aubio.js](https://github.com/qiuxiang/aubiojs), and [Vite](https://vitejs.dev).
Inspiration: TouchDesigner VJ workflows, the OIIA cat meme.

## License

MIT. Fork it, remix it, ship your own DJ tooling. See [LICENSE](LICENSE).
