# Changelog

All notable changes to this project will be documented in this file.

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
