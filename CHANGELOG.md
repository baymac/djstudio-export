# Changelog

All notable changes to this project will be documented in this file.

## [0.1.6.1] - 2026-06-03

### Changed
- **Docs:** Restructured the README around what each command's user needs. Every section now follows the same shape — what it does, how to run it, the **Setup** you do once (credentials, prerequisites, app-must-be-closed constraints), and **Good to know** (the tradeoffs and caveats: SoundCloud/Bandcamp fidelity, Apple Music best-effort re-add, `enrich analyse` timing/memory and what it doesn't produce, `--threshold` tuning, etc.). Engine internals that users don't need (token-refresh mechanics, byte-verification, internal function/file names) were dropped or demoted, while the config and tradeoffs that were buried in them are now surfaced explicitly. The DB schema and command tree are kept in full (you need them for `export --query`).
- **Docs:** Reframed the README enrichment section around `dj enrich metadata` as a single entrypoint that enriches **both** detected (`detected_tracks`) and synced (`sync_tracks`) sources by default, scoped with `--detect`/`--sync`. Clarified that both sources land in the same `enriched_tracks` table and cleaned up the command examples to drop the stale `--detect`-on-every-line framing.

## [0.1.6.0] - 2026-06-03

### Added
- **Bulk restore — rebuild a source app from the `dj.db` backup** (`dj sync <app> playlist push` with restore scopes, `sync/restore.py`). The inverse of `playlist delete`, run library → playlists → favorites. **Apple Music**: `--playlists` recreates each captured playlist (matches in-library tracks), `--library` repopulates the library, `--favorite-only` re-marks captured favorites as loved, `--all` does all three; `--readd-missing` skips tracks already in the library so a catalog re-add is idempotent and resumable. Catalog re-add (`--library`/`--favorite-only`) is best-effort via the `itmss://` trick — region-locked or removed tracks can't be re-added on macOS and are skipped. **Spotify**: `--playlists` recreates each playlist, `--library` re-saves Liked Songs, `--all` does both — exact (the Web API adds by id, no re-add hack). **Beatport**: `--all`/`--playlists` recreate every captured playlist on the account.
- **`Spotify.save_tracks`** — add tracks to Liked Songs (`PUT /me/tracks`, batched by 50, idempotent), backing `spotify playlist push --library`.

### Changed
- **`dj sync music|spotify` now captures everything by default** — with no scope flag, capture grabs all playlists + the library (Apple Music: + Favourite Songs). `--library` and `--favorite-only` now *narrow* to just that collection and are combinable; `--all` is the explicit form of the default. A named `--playlist` still narrows to one playlist. `--favorites` is kept as an alias of `--favorite-only`. `dj sync beatport` gains a no-op `--all` for symmetry.

### Removed
- **`dj sync music check-connections` and `list-playlists`** — dead subcommands (and their MusicKit bridge wrappers `run_bridge`/`check_musickit`/`list_playlists`) removed.


### Added
- **`dj export set <id> --to bp_chart|bp_playlist|rekordbox`** — push a stored set's tracks, in set order, to a publishable Beatport chart (created as an unpublished draft), a Beatport playlist, or a rekordbox playlist. `--name` overrides the destination name; `--description` (chart only) defaults to a line built from the set's mood/duration/archetype; every destination accepts `--dry-run`.
- **`dj-set-builder` skill + `helpers/build_set.py`** — curate and sequence a DJ set from the analysed library along an energy-curve **archetype** (11 to start: warm-up, peak-time, late-night, closing, club-night, sunset, party, dark, festival, dinner, morning-coffee), each with default genres and a multi-phase non-monotonic intensity curve. Sequencing walks a **composite intensity** (`0.60·mik_nrg + 0.25·bpm + 0.15·drum/bass drive`, pool-relative) greedily while keeping tracks Camelot-harmonic and tempo-smooth, matching stem texture to each phase, and spacing artists/labels. Track count is clamped to `[duration/5, duration/2]`. The set is stored in the new `dj_sets` / `dj_set_tracks` tables (provenance in `params_json`) and addressed by a returned id; building is fully decoupled from export.
- **`--date-blend` proportional release-date mix** — any number of date ranges each with a ratio (`[{"from","to","ratio"}...]`); the set is filled to ~each ratio (capped to pool supply, shortfall refilled). Omitting it applies the default 75% ≤1yr / 12.5% 1–2yr / 12.5% older blend. The skill turns free text ("may 2026 50%, jan 30%, feb 20%") into this JSON.
- **`dj export beatport|rekordbox --query SQL --name NAME`** — ad-hoc SQL-curated push (the former `dj playlist`), now living under `dj export` alongside `set`.
- **Beatport chart support** — new chart API methods (`list_my_charts`, `create_chart`, `update_chart`, `list_chart_track_ids`, `add_chart_track`) so charts can be created, reused, and filled in order without disturbing playlists.
- Auto-saved credentials for `detect instagram` / `detect mixcloud` — a successful (or freshly provided) login is persisted and reused on the next run.

### Changed
- **Push targets consolidated under `export/`** — `playlist/to_beatport.py` and `playlist/to_rekordbox.py` are now `export/to_beatport.py` and `export/to_rekordbox.py`, the single home for "write tracks to a destination" shared by all `dj export` verbs. `playlist/` now only carries `query.py` (SQL → rows), consumed by the export query verbs.
- **`dj playlist` retired → `dj export`** — `dj playlist beatport|rekordbox` became `dj export beatport|rekordbox` (same `--query`/`--name`/`--dry-run` flags). Top-level `dj playlist` is removed.
- SoundCloud auth is now automatic from `SOUNDCLOUD_CLIENT_ID/SECRET`; the one-time user-OAuth flow is the `connections.soundcloud.login_user()` helper rather than a CLI command.

### Removed
- **Rekordbox phrase round-trip** — `detect export-to-rekordbox` (Stage 6a) and `detect import-rekordbox-analysis` (Stage 6b) and their modules. The `rk_analysis_json` / `rekordbox_export_at` / `rekordbox_analysis_at` columns remain for pre-existing data but are no longer written, and `playlist/query.py` no longer selects `rk_analysis_json`. Push a curated set to rekordbox with `dj export set <id> --to rekordbox`.
- **Read-only browse commands** — `detect history`, `detect sessions`, all `detect *-history`, `detect enriched`, `detect enrich-runs`, `detect enrich-tracks`. Query `~/Music/dj/dj.db` directly for inspection. The mutating `detect *-delete-session` commands stay.
- **`detect login-instagram` / `login-mixcloud` / `login-soundcloud`** — folded into the detect/auth flow (see Changed / auto-saved credentials above).

### Fixed
- `.gitignore` no longer carries a stray trailing backslash on the `!package.json` rule; the `dj-set-builder` skill is now tracked instead of ignored.

## [0.1.4.0] - 2026-05-29

### Added
- **`dj extension pack <name>`** — zip any Chrome extension under `apps/<name>-extension/` into a Web Store-ready archive at `~/Music/dj/extensions/<name>-extension-v<version>.zip`. Version is read from the manifest; entries use a fixed 1980-01-01 timestamp so re-runs over unchanged sources produce byte-identical zips. Drag the zip onto `chrome://extensions` (Developer mode) to load it, or extract and "Load unpacked". Run `dj extension pack 1001T` to package the bundled 1001tracklists PiP extension.

## [0.1.3.2] - 2026-05-23

### Added
- **`vj/cats` live demo** — deployed to [cats-two-gold.vercel.app](https://cats-two-gold.vercel.app); README updated with live demo link and `.vercel` added to `.gitignore`
- **Blog link in README** — added `## Blog` section linking to the [dj detect enrich deep-dive](https://www.baymac.lol/posts/dj-detect-enrich) post

## [0.1.3.1] - 2026-05-23

### Changed
- **README setup section** — added `source .venv/bin/activate` step so new users know how to put `dj` on their PATH after `uv sync`; corrected playwright install comment (Beatport login removed; real consumers are SoundCloud browser fetch and `helpers/download_course.py`)
- **Sub-project READMEs** (`vj/cats/`, `apps/1001T-extension/`) — added one-line backlinks to the root README Setup section so users who land directly on a sub-folder README know where to install dependencies
- **CLAUDE.md** — corrected playwright install comment to match current consumers

## [0.1.3.0] - 2026-05-23

### Added
- **VJ visualizer** (`vj/cats/`) — audio-reactive browser visualizer built around the DJ's cats; procedural cat poses in WebGL, real cat photos that dance to the music, and cinematic AI videos that ping-pong loop; Vite + p5.js + Meyda + aubio.js, runs entirely in the browser
- **`dj vj <name> start/stop`** CLI subcommand — auto-discovers any `vj/<name>/` subdirectory with a `package.json` dev script and runs it via portless at `https://<name>.localhost`; no code change needed to add new VJ apps
- **MIT LICENSE** — project is now open-source (fork it, remix it, ship your own DJ tooling)
- Credits section in README (`baymac` / JAKE FURY) and acknowledgments for p5.js, Meyda, aubio.js, Vite, and the OIIA cat meme

### Changed
- `pyproject.toml` — `vj*` added to `setuptools.packages.find` so the installed `dj` script finds `vj.cli`
- README — VJ visualizer section added; layout section updated; Credits + License section appended

## [0.1.2.0] - 2026-05-23

### Added
- **Multi-browser cookie reader** (`connections/cookies.py`) — replaces Brave-only `brave_cookies.py`; wraps `browser_cookie3` for Brave, Chrome, Chromium, Edge, Opera, Vivaldi, Firefox, and Safari; two helpers: `read_cookies_for_domain` (Playwright-shaped dicts) and `load_cookie_jar` (httpx/requests CookieJar)
- **1001tracklists auto-fetch** (`detect/tracklists1001_api.py`) — POSTs to `export_data.php` using browser cookies instead of requiring vi-paste; supports `--browser {brave,chrome,safari,firefox}` flag with automatic fallback to vi-paste on failure
- `--paste` flag on `detect 1001tracklists` to force legacy vi editor flow
- `browser-cookie3` dependency

### Changed
- `detect 1001tracklists` now auto-fetches via Brave cookies by default; falls back to vi-paste on any error
- `connections/beatport.py` and `connections/soundcloud_browser.py` updated to import from `connections.cookies` instead of the removed `brave_cookies`

### Removed
- `connections/brave_cookies.py` — superseded by `connections/cookies.py`

## [0.1.1.0] - 2026-05-17

### Added
- **Spotify source** (`detect spotify <url|name>`) — import any Spotify playlist directly into detected_tracks by URL or interactive search; handles pagination and 429 rate-limit backoff
- **1001tracklists source** (`detect 1001tracklists <url>`) — scrape tracklists from 1001tracklists.com with vi editor input
- **Gems finder** (`detect gems`) — discover low-play hidden-gem tracks across Spotify, SoundCloud, Bandcamp, and Beatport; approve/reject flow persists only approved tracks; rejected tracks go to `rejected_gems` and never resurface
- **yt-dlp multi-browser cookie fallback** — tries Brave → Chrome → Safari → Firefox automatically on YouTube/SoundCloud bot detection; caches the working browser for a week
- **Text source** (`detect text`) — import plain-text tracklists (numbered or timestamped) via vi editor
- **SoundCloud source** with OAuth + yt-dlp fallback (`detect soundcloud <url>`)
- **topdjmixes source** (`detect topdjmixes <url>`)
- **fix-session command** — correct a detected session's tracklist using a pasted confirmed list; fuzzy-matches and removes mismatches
- **dry-run flag** across all audio sources (radio-garden, mixcloud, etc.)
- **caffeinate** context manager — prevents macOS idle sleep during long-running commands (studio-analyse, enrich, radio-garden)
- `rejected_gems` table — stores rejected tracks so they never surface in future scans

### Changed
- **Spotify gems scan** — fetch each playlist once (5 playlists max), filter in-memory; eliminates 33-call burst that triggered 429 bans; adds `Retry-After` handling that bails immediately on long bans (>120s)
- **seen_ids bug fix** — popularity threshold widening passes now reset `seen_ids` so tracks rejected at a lower threshold are re-evaluated at higher ones
- studio-analyse + rekordbox push hardening; JWT auto-refresh without helper restart
- Beatport CDP login + curl_cffi token refresh
- Version-variant dedup across enrich and all audio sources

### Fixed
- `detect/spotify.py` `_fetch_playlist_tracks` silently truncated imports on HTTP 429 — now backs off with `Retry-After` like the gems sibling
- `detect/cli.py` fix-session had duplicate `det_to_conf[di] = ci` assignment (harmless but noisy)
- `tests/test_radio_caffeinate.py` — `_radio_args()` missing `dry_run` field, causing test failures after radio dispatch was updated

## [0.1.0.0] - 2026-04-01

### Added
- Unified `dj` CLI: `detect`, `sync`, `playlist` subcommands
- Beatport sync pipeline (Stages 1–6): Apple Music → Beatport metadata → DJ Studio analysis → rekordbox
- DJ Studio SDK headless analysis via Node helper
- Rekordbox PSSI/cue import
- SQL-curated playlist push to Beatport and rekordbox
- uv-based project setup with pytest test suite
