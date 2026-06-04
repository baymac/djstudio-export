# CLAUDE.md

Guidance to Claude Code for this repository.

## Project Overview

Unified DJ tool. Builds a fully-analysed track library by progressively enriching each track with Beatport metadata and DJ Studio analysis (key/energy/stems). Build energy-sequenced sets with `dj set build`, then push any stored set or SQL-curated subset to a Beatport chart/playlist or a rekordbox playlist.

All tool-generated files live under `~/Music/dj/` (DB at `dj.db`, per-command logs at `logs/<cmd>/`, state at `state/`, etc). `paths.py` is the single source of truth and auto-migrates old locations on first import.

See `README.md` for the full pipeline narrative + flag reference. This file only covers things that aren't obvious from reading the code.

## Layout

```
dj_cli.py                       CLI entrypoint — detect / sync / enrich / export / course / vj

connections/                    Transport layer (no app-specific deps)
  beatport.py                   Beatport HTTP client + Playwright session token capture
  matching.py                   Fuzzy title/artist matching
  musickit.py                   Swift MusicKit bridge subprocess wrapper
  bridge/musickit_bridge.swift  Compiled on first use, cached

detect/                         Track detection pipeline
  db.py                         All detect+enrich DB operations
  cli.py                        argparse subcommands + async dispatch
  gems.py                       detect gems: low-play track discovery (Spotify/SoundCloud/Bandcamp/Beatport)
  sync_beatport.py              pull Beatport library → enriched_tracks
  instagram.py / mixcloud.py / youtube.py / soundcloud.py / radio.py /
  podbean.py / reddit.py / topdjmixes.py
                                per-platform capture (Shazam-based for
                                audio sources, paste-into-vi for reddit/topdjmixes)
  shazam.py / parser.py         Audio recognition + tracklist parsing

sync/                           Faithful capture of source-app playlists (Apple Music / Spotify)
  capture.py                    `dj sync <app> pull`: playlists/library → sync_tracks + sync_playlist_tracks
  push.py                       `dj sync <app> push --name`: selected sync_tracks → recreate an app playlist
  restore.py                    `dj sync <app> push --all/--playlists/--library`: rebuild the app from the dj.db backup
  enrich_adapter.py             `dj enrich metadata --sync` adapter: drives enrich/engine over sync_tracks
  db.py / cli.py                canonical track store + membership; argparse dispatch (pull/list/push/delete)

enrich/                         Unified enrichment + DJ Studio analysis
  cli.py                        `dj enrich metadata` (default both; --detect/--sync to scope) + `dj enrich analyse`
  engine.py                     shared enrich engine (detected/synced → Beatport metadata)
  analyse.py                    DJ Studio SDK analysis → enriched_tracks_analysis
  studio_sdk.py                 Shared SDK driver: SdkHelper + _shape_result + token decrypt
  dj_studio_sdk.js              Long-running Node helper for the analysis SDK

playlist/                       SQL → rows helper (consumed by `dj export beatport|rekordbox`)
  query.py                      Run user SQL → list[beatport_id] + full-row fetch

set/                            Energy-curve set builder
  cli.py                        `dj set build` — sequence tracks along an archetype intensity curve

export/                         The single home for pushing tracks out
  to_beatport.py                push_to_beatport (playlist) + push_to_beatport_chart
  to_rekordbox.py               push_to_rekordbox
  export_set.py                 Resolve a stored set id → push to bp_chart/bp_playlist/rekordbox
  cli.py                        `dj export set <id> --to ...` + `dj export beatport|rekordbox --query --name`

djstudio/                       Read DJ Studio's local files (used for ad-hoc inspection)
  extractor.py                  audio-library-table + projects-table reader
  keys.py                       Camelot conversion

rekordbox/                      Rekordbox writes via pyrekordbox
  backup.py                     master.db backup before any write
  constants.py                  Path discovery + Camelot/cue-kind constants

apps/                           Frontend apps backed by `dj` CLI commands
  course/                       Vite + React offline course viewer
    cli.py                      `dj course start/stop` — spawns vite via portless
    src/                        React app (TanStack Router, video + quiz playback)
    vite.config.ts              publicDir = ~/Music/dj/; reads PORT/HOST
                                env vars set by portless

helpers/                        Standalone maintenance scripts
tests/                          pytest
```

## Commands

```bash
# Setup
uv sync
uv run playwright install chromium  # needed for SoundCloud browser fetch + helpers/download_course.py

# Tests
uv run pytest

# Pipeline (see README.md for full flow)
uv run dj_cli.py sync music pull                                                        # capture everything from Apple Music → sync_tracks (faithful)
uv run dj_cli.py sync music pull --library                                              #   only library + Favourite Songs (--playlists / --all are the other scopes)
uv run dj_cli.py sync spotify pull                                                       # capture all Spotify playlists + Liked Songs → sync_tracks
uv run dj_cli.py detect youtube <url>
uv run dj_cli.py detect gems --source beatport --genre "Tech House" --count 10 --date 1mo  # discover low-play tracks → detected_tracks
uv run dj_cli.py sync beatport pull                                                     # pull Beatport library → enriched_tracks
uv run dj_cli.py enrich metadata                                                        # enrich detected + synced tracks → enriched_tracks
uv run dj_cli.py enrich metadata --detect                                               #   only detected tracks (or --sync for synced)
uv run dj_cli.py enrich analyse                                                         # SDK → enriched_tracks_analysis
uv run dj_cli.py enrich analyse --ids 12345,67890 --force --verbose                     #   re-process specific tracks (debugging)

# Build an energy-sequenced set (the dj-set-builder skill drives this interactively)
dj set build --list-archetypes                                                          # catalogue + default genres
dj set build --archetype club_night --duration 120                                      # preview (no write)
dj set build --archetype party --name "Bday" --duration 90 --count 24 \
    --genres "House,Tech House" --date-blend '[{"from":"2026-01-01","ratio":0.9},{"to":"2025-12-31","ratio":0.1}]' \
    --save                                                                              # -> set_id=<n>

# SQL → destination (Beatport playlist or rekordbox)
uv run dj_cli.py export beatport  --query "SELECT beatport_id FROM enriched_tracks WHERE ..." --name "..."
uv run dj_cli.py export rekordbox --query "..." --name "..."

# Stored set → destination (set id comes from the dj-set-builder skill / dj set build)
uv run dj_cli.py export set <id> --to bp_chart                       # publishable Beatport chart (draft)
uv run dj_cli.py export set <id> --to bp_playlist --name "Peak Time" # Beatport playlist
uv run dj_cli.py export set <id> --to rekordbox --dry-run            # rekordbox playlist (quit rekordbox first)

# Course viewer (offline)
dj course start                                                                         # spawn vite via portless, open https://course.localhost
dj course stop                                                                          # kill the background process group

# Maintenance
uv run helpers/cleanup_playlist.py "Playlist Name" --dry-run
```

## Key Design Decisions

### Enrichment pipeline (detect + sync)

- **Two enriched tables, no mirror** — `enriched_tracks` carries everything Beatport-derived (basic search-result fields + the 6 catalog-detail extras). `enriched_tracks_analysis` is sparse: keyed on `beatport_id`, holds DJ Studio analysis (`mik_key`, `mik_nrg`, per-stem `*_avg`/`*_peak`, `analysis_json` with full energy segments + 1Hz stem curves + per-segment stem RMS) + rekordbox PSSI (`rk_analysis_json`) + per-stage timestamps. A row exists in the analysis table only after `enrich analyse` has populated it. Joins (e.g., `enriched_tracks LEFT JOIN enriched_tracks_analysis USING(beatport_id)`) build the full picture at query time.
- **Beatport metadata in one place** — Full track-detail (label, ISRC, mix_name, sub_genre, length_ms, catalog_number) is fetched **only** in `enrich/engine.py` (and inline-extracted from playlist responses by `detect/sync_beatport.py`) and lands directly on `enriched_tracks`. `enrich analyse` must not call Beatport. Reason: `enrich analyse` already runs a long Node helper; an extra Beatport client + token-refresh path there is what caused the prior mid-run token-expiry incident.
- **Rekordbox phrase round-trip removed** — the old round-trip (`detect export-to-rekordbox` → manual analyze → `detect import-rekordbox-analysis`) is gone. The `rk_analysis_json`, `rekordbox_export_at`, `rekordbox_analysis_at` columns remain in `enriched_tracks_analysis` for any pre-existing data but are no longer populated, and `playlist/query.py` no longer selects `rk_analysis_json`. Push a curated set to rekordbox with `dj export set <id> --to rekordbox` instead. `db.mark_pipeline_done` survives (generic stamp guard) but nothing calls it now.
- **enrich analyse writes only to our DB** — `enrich analyse` calls `upsert_analysis(beatport_id, fields)` to populate `enriched_tracks_analysis` (stamps `dj_studio_at` on insert). DJ Studio's filesystem is never touched. The skip-rule for re-runs is "row exists in `enriched_tracks_analysis` for this beatport_id" (override with `--force`); for ad-hoc reruns of specific tracks pass `--ids ID,ID,...`. SDK output was previously verified byte-for-byte against DJ Studio's stored values: mikKey/mikEnergy/BPM/duration/beat-count/energy segments all match exactly. The two divergences DJ Studio applies (rounded BPM, segment merging, cue-point trimming, BP-key override of mikKey for certain tracks) are display-time post-processing — we keep the fuller raw signal.
- **JWT auto-refresh** — DJ Studio's access JWT lives ~60 min; long runs hit expiry. On a 401 from `cf.dj.studio`, `enrich analyse` re-decrypts `encryptedToken-v2.dat`, re-exchanges via `app-services.dj.studio`, and pushes the fresh JWT down to the running Node helper via the `setAccessJwt` command (defined in `dj_studio_sdk.js`). No helper restart, no model reload. Hard-abort only fires if the post-refresh retry ALSO 401s — at that point `encryptedToken-v2.dat` itself is invalid and only "open DJ Studio, sign in" can fix it.
- **DJ Studio analysis is headless via SDK** — `enrich/studio_sdk.py` decrypts DJ Studio's local refresh token (AES-256-CBC, hardcoded key in `encryptedToken-v2.dat`), exchanges it for a JWT via `app-services.dj.studio`, then drives `dj_studio_sdk.js` (a long-running Node helper that loads `@appmachine/beatport-sdk` + `@appmachine/ai-stems` (Demucs) + `@appmachine/ai-beatgrid` + the MIK WASM extractor and calls `cf.dj.studio/mixedinkey/analyze`). The Demucs model weights live at `~/Library/Application Support/DJ.Studio/extensions/djs-stems/models/htdemucs_fast_encrypted.pt` — installed by DJ Studio itself, shared by us. DJ Studio must be quit (port 61894 + `.beatport/` cache locks).
- **Stem curves + per-segment RMS** — the Node helper computes per-1024-sample-bucket RMS (~23ms resolution) per stem when running Demucs and ships them back as base64 uint16. `_shape_result` decodes them into (a) `stems[stem].curve_1hz` — one mean RMS per second of audio, ~300 floats per stem for a 5-min track, used for "where does X come in?" queries — and (b) `stems[stem].per_segment` — index-aligned with `energy.segments[]`, for "vocals during the chorus" queries. Both live in `analysis_json`.
- **No phrase labels** — DJ Studio's `track-structures-table.phraseData` is always empty (the renderer never calls the dormant ML phrase model), so `enrich analyse` yields no semantic phrase labels. The rekordbox PSSI round-trip that used to supply Intro/Verse/Chorus/Outro labels has been removed, so the library currently carries no phrase labels.
- **Beatport access token refresh** — `BEATPORT_ACCESS_TOKEN` ~10 min, `BEATPORT_SESSION_TOKEN` ~32 days. The session token auto-refreshes the access token on 401. Don't add manual refresh wrappers around individual stages — `connections/beatport.resolve_access_token` handles the cascade (env access token → env session cookie → browser cookie store). `connections/beatport.refresh_via_session(verbose=True)` (or `BEATPORT_DEBUG=1`) prints the real cause when refresh fails — `RefreshAccessTokenError` from NextAuth means the server-side refresh chain is broken; sign out and back into beatport.com in the default browser to rotate the session cookie.
- **One verb set per app: `dj sync <app> pull | list | push | delete`** — every source app (music/spotify/beatport) exposes the same four verbs with the **same three scope flags**, defined once in `sync/cli.py:_add_scope_flags` (`--playlists | --library | --all`, dest=`scope`). The scope means the same thing for every verb: **`--playlists`** = all user playlists, EXCLUDING the personal collection (Apple Music: excludes Favourite Songs; Spotify: excludes Liked Songs); **`--library`** = the personal collection (Apple Music: library songs **+ Favourite Songs**; Spotify: Liked Songs); **`--all`** = both. Beatport has only `--all` (no library/liked concept). `pull` defaults to `--all`; `delete` requires an explicit scope; `push` takes a scope (bulk restore) or `--name --ids/--query` (ad-hoc). `run_sync_music`/`run_sync_spotify` take `scope=` (not the old per-collection booleans), and `_sync_before_delete(app, scope)` backs up via the **same** `pull` entrypoint with the **same** scope, so the pre-delete backup log is identical to a real `pull` and only re-captures what's being deleted.
- **Sync capture is a non-destructive split, mirroring the Beatport side** — `dj sync <app> pull` writes to two tables (`sync/db.py`): **`sync_tracks`** is the canonical per-`(app, dedup_key)` track store (native id when present, else normalised artist+title), append-only/upsert — a track row is **never** deleted by a re-sync, so a delete on the source app can't destroy captured data; enrich state (`enrich_outcome`, `enriched_beatport_id`) lives here once per unique track. **`sync_playlist_tracks`** holds playlist→track membership links + position. `replace_playlist` re-snapshots only a playlist's membership (positions rewritten, removed tracks lose their link but keep their canonical row); it returns `{new, kept, removed, total}` for the per-playlist `+N new, M skipped` log line. **There is intentionally no DB-side delete** — `dj.db` is the permanent backup. `dj sync <app> delete` removes from the **source app** (Apple Music via AppleScript `delete playlist`, Spotify via unfollow `DELETE /playlists/{id}/followers`, Beatport via `DELETE /my/playlists/{id}/`), never from our DB; it only deletes what's been captured, offers to **pull-first** so the backup is current, then asks **once** before the (irreversible) delete. Scope→action: **`--playlists`** deletes the user playlist containers (Apple: by name, deduped; Spotify: unfollow by id); **`--library`** clears the personal collection — Apple `clear_apple_library()` (batched AppleScript wipe of `library playlist 1`, which also removes Favourite Songs since they're library tracks), Spotify `clear_saved_tracks()` (batched `DELETE /me/tracks`); **`--all`** does both. The `__library__`/`__favorites__` pseudo-playlists are **never** playlist-delete targets — they belong to the `--library` scope; `_playlist_delete_targets` excludes both pseudo-ids and (for Apple) the "Favourite Songs" name from the `--playlists` set. One un-deletable playlist (e.g. a smart/managed one → AppleScript `-10003`) is caught per-target and skipped, not fatal. `init_db()` auto-migrates a pre-split flat `sync_tracks` on first run. The legacy `synced_tracks`/`sync_runs` tables are gone.
- **"Favourite Songs" is captured once, via `--favorites` only** — the Swift bridge's `streamAllPlaylists()` (`--all-playlists`) now skips the playlist named "Favourite Songs" (mirroring the existing `--list-playlists` filter), so faithful playlist capture no longer ALSO grabs it under its real streamed id. It lands only under the `__favorites__` pseudo-id (via `--favorites`, the authoritative loved-songs set). Before this fix it appeared twice (once under `__favorites__`, once under the real id with a slightly different count); the stale duplicate rows were deleted from `dj.db` directly.
- **Apple Music playlist *restore* (`dj sync music push`) matches by persistent id → name+artist+album, by macOS necessity** — on macOS MusicKit cannot write the library: `MusicLibrary.createPlaylist` AND `MusicLibrary.add` are both `@available(macOS, unavailable)` (verified by `swiftc -typecheck`), so the only write path is scripting Music.app, and AppleScript cannot reference a track by its Apple Music **catalog id** (a cloud track exposes only `name`/`artist`/`album`/`database ID`/`persistent ID` — no store id). So the stable identifier we use is the AppleScript **`persistent ID`**: MusicKit doesn't provide it, so capture reads it from Music.app (`musickit.read_playlist_persistent_ids`) and attaches it to each captured row position-by-position, but **only when the two enumerations agree exactly** (same length + same track name at every index; ambiguous duplicate-named playlists and any read error → unset). It lands in the additive nullable `sync_tracks.native_persistent_id` (COALESCE-preserved, never overwritten with NULL). `build_create_playlist_applescript` then matches per track in order: (1) exact `whose persistent ID is …` (collision-proof, survives metadata edits), (2) fallback `name + artist` with captured `album` as a tiebreaker when several library tracks collide. For a track that has **left the library**, name+artist/persistent-id can't match it — the only macOS path to put it back is the best-effort `itmss://` store-URL trick (see the restore bullet); otherwise it's dropped, surfaced via `added < requested`. Do not re-attempt a "match by catalog id in AppleScript" path — the catalog id isn't reachable from AppleScript.
- **Bulk restore is the inverse of capture (`dj sync music push --all/--playlists/--library`, `sync/restore.py`)** — rebuilds Apple Music from the `sync_tracks` backup, run in order library → playlists → favorites. The CLI scope maps to restore.py's internal scope set via `_restore_scopes(app, scope)`: Apple Music **`--library`** → `{library, favorites}` (the personal collection covers Favourite Songs), **`--playlists`** → `{playlists}`, **`--all`** → all three. **playlists** recreates each captured user playlist via `create_apple_playlist` (matches tracks already in the library — the reversible round-trip for a `delete --playlists`). **library** repopulates the library from `__library__` rows and **favorites** re-marks `__favorites__` rows as `loved` (`musickit.mark_loved`); both reach tracks not in the library only through `musickit.readd_track_by_catalog_id` — the **best-effort, EXPERIMENTAL** `itmss://itunes.apple.com/song?id=<native_track_id>` open (the only macOS catalog re-add; MusicKit `add` is unavailable). **`--readd-missing`** drops tracks already in the library (matched by name+artist via `read_library_track_keys`, since a re-added track gets a *fresh* persistent id) so the re-add is idempotent and resumable (Ctrl-C, re-run). Region-locked/removed tracks never re-add — accepted. **Spotify & Beatport restore are exact** (real APIs add by id, no `itmss://` hack): **spotify** `--playlists` → `{playlists}` recreates each captured playlist (`create_playlist` + `add_tracks`), `--library` → `{library}` re-saves Liked Songs (`spotify.save_tracks` → `PUT /me/tracks`), `--all` = both (no `--readd-missing` — Liked Songs *is* the library); **beatport** `--all` (its only scope) recreates every `beatport_playlists` row on the account from `detect.db.beatport_track_ids_in_playlist` via `beatport.create_playlist` + `add_track`. `restore_music`/`restore_spotify`/`restore_beatport` all live in `sync/restore.py`; the legacy `helpers/{export,restore,clear}_apple_music.py` scripts are superseded by this + `sync <app> delete`. Restore only adds — nothing destructive on its own.
- **`--library` cursor** — `dj sync music pull --library` tracks the last `library_added_date` processed in the `cursors` table (key `apple_music_library`); re-runs only capture new Apple Music additions.
- **`connections/cookies.py` is the single cookie reader** — wraps `browser_cookie3` to support Brave, Chrome, Chromium, Edge, Opera, Vivaldi, Firefox, Safari. Two helpers: `read_cookies_for_domain(domain, browser)` returns Playwright-shaped dicts (used by `connections/soundcloud_browser.py` and `connections/beatport._read_beatport_cookies_from_browser()`); `load_cookie_jar(domain, browser)` returns an `http.cookiejar.CookieJar` (used by `detect/tracklists1001_api.py` for httpx). `helpers/download_course.py` is intentionally separate — it sniffs Dyntube AES key bytes from a live Playwright context, not cookies, so the static-cookie path doesn't apply.
- **`detect 1001tracklists` uses Brave cookies by default** — `detect/tracklists1001_api.py` POSTs to `export_data.php` with cookies loaded via `connections/cookies.load_cookie_jar`. On any failure it falls back to the vi-paste path automatically. `--paste` forces vi; `--browser {brave,chrome,safari,firefox}` selects the source profile (no auto-fallback chain — if Brave fails, re-run with `--browser chrome`).
- **yt-dlp cookie auth (YouTube/SoundCloud fallback)** — `detect/youtube.py` uses `--cookies-from-browser BROWSER` live (never a cached Netscape file) because yt-dlp 2025 requires a **po_token** (Proof-of-Origin Token) that is only available from a live browser session; a static cookie file causes YouTube to return "Sign in to confirm you're not a bot" even with valid session cookies. Browsers are tried in order (Brave → Chrome → Safari → Firefox); the first one that works is cached in `~/Music/dj/state/yt_browser.txt` for a week. On bot detection, the next browser in `_BROWSERS` is tried automatically. If all browsers fail, the error tells the user to log in to YouTube in one of them. Never hardcode a single browser name — the ordered fallback list lives in `_BROWSERS`.
- **`fix-session` safe-delete rules** — `db.remove_tracks_from_session` unlinks a track from a session and deletes it from `detected_tracks` only when all three conditions hold: (a) no other `track_sessions` row references it, (b) no `enriched_tracks` row has it as `detected_track_id`, and (c) its `source` is not `'beatport'`. This means enriched tracks and Beatport-sourced tracks are never deleted, only unlinked.
- **caffeinate on long-running commands** — `caffeinate.py` (top-level) provides a `caffeinate()` context manager that runs `caffeinate -i` to prevent macOS idle sleep. Applied to: `enrich analyse` (Node SDK analysis, ~23s/track, can run hours over a full library), `enrich metadata` (sequential Beatport API calls, can run 20+ min on large libraries), `detect radio-garden` (indefinite monitoring loop). The macOS power assertion is released automatically when the `caffeinate` process exits. Not needed for fast filesystem-only commands (`dj export ...`).

### Discovery (detect gems)

- **`detect gems` review flow — nothing is saved without approval** — after a scan, `review_gems` walks the found tracks one at a time, printing each track's link so the user can listen, then prompts approve / reject / skip / quit. Only **approved** tracks are persisted to `detected_tracks` (via the normal `insert_track` dedup path, so they flow into `enrich` like any other detected track) — that write also creates a `sessions` row (`type='gems'`, synthetic `gems://<source>/<genre>?t=<iso>` URL to satisfy the `UNIQUE(url)` constraint) + a `gem_scans` row + per-track `gem_tracks` rows. **Rejected** tracks go to the `rejected_gems` table instead and never enter the pipeline. **Skipped/undecided** tracks aren't persisted anywhere, so they can reappear in a later scan. `--no-save` shows the results table and skips review entirely (testing only).
- **Cross-run dedup is content-based, not offset-based** — platform results reshuffle over time, so the next run can't trust a page offset. `db.seen_gem_keys(source, cutoff)` + `db.seen_rejected_gem_keys(source, cutoff)` build a combined exclude set of prior approved + rejected `(artist, title)` keys, and each search pages until `--count` *new* tracks are collected. Both approved and rejected gems with a release date older than the current `--date` cutoff are "faded" (dropped from the comparison set — they can't recur in a window that excludes them anyway); `gem_tracks` and `rejected_gems` are both indexed on `(source, release_date)` for this. Dedup is per-platform — safe because `enrich`'s `upsert_enriched` collapses cross-platform duplicates by `beatport_id`.
- **Per-platform gem signal differs** — Beatport filters by exact `genre_id` (only authoritative genre source) and drops Hype (label-paid promotion) tracks since it has no public play count; SoundCloud filters `playback_count < 5000`; Spotify mines editorial playlists by `popularity` (its `genre:` search filter is unreliable for sub-genres); Bandcamp filters by uploader `tag_norm_names` via `discover/1/discover_web` (the older `discover/3/get_web` silently ignored the tag param, returning every genre). Genre IDs / tag mappings live in `detect/gems.py` — extend `_BEATPORT_GENRE_IDS` / `GENRES` to add genres.

### Apps (`dj course`, `dj extension`)

- **`apps/<name>/cli.py` pattern** — each frontend app gets a sibling Python CLI that's mounted into `dj_cli.py` as a top-level subcommand (`dj course start/stop`). `apps/` is a Python package (has `__init__.py`) and must be listed in `pyproject.toml`'s `[tool.setuptools.packages.find]` `include` array, otherwise the installed `dj` script in `.venv/bin/` raises `ModuleNotFoundError: No module named 'apps'` even though `uv run dj_cli.py` works.
- **`dj extension pack <name>`** — generic Chrome extension packer (`apps/extension/cli.py`). Resolves the source folder by trying `apps/<name>-extension/extension/`, then `apps/<name>/extension/`, then `apps/<name>/` — first hit with a `manifest.json` wins. Writes a deterministic zip to `~/Music/dj/extensions/<short>-extension-v<manifest-version>.zip` (entries stamped 1980-01-01 so unchanged sources produce byte-identical archives). The exclude list is intentionally narrow (`.DS_Store`, `._*`, `__MACOSX/`, `node_modules/`, `.git/`) so a manifest-referenced file is never silently dropped. The output is a Chrome Web Store-ready zip; for a signed `.crx`, use chrome://extensions → "Pack extension" on the extracted folder.
- **portless wrapping** — `dj course start` runs `npx portless course npm run dev` in a new process group (`start_new_session=True` so `pid == pgid`; stop kills the whole group with `os.killpg`). Portless picks a free port, sets `PORT=<port> HOST=127.0.0.1` env vars, then exec's the dev command. `apps/course/vite.config.ts` reads those env vars (`process.env.PORT/HOST`) so vite binds to portless's port; if vite ignores them (the default) the proxy gets a 502 because portless registers one port and vite picks another.
- **stdout piped to a log file, not DEVNULL** — portless detects the dev server's URL by parsing its stdout. If we redirect to `subprocess.DEVNULL` portless can't see the "Local: …" line and ends up routing to a random port → 502. The CLI redirects to `~/Music/dj/logs/course/YYYYMMDD_HHMMSS.log` so portless still sees the output. After startup the URL is extracted from the same log with a `-> https://…` regex and saved to `~/Music/dj/state/course_url.txt` for `_get_url()`. `npx portless get <name>` is **not** used — in a git worktree it returns a worktree-prefixed URL (`https://minsk-v10.course.localhost:1355`) that portless never actually registers a route for, so it 404s.
- **Service install is optional** — without `npx portless service install` the proxy runs on port 1355 (no root needed) and URLs include `:1355`. With it, port 443 binds at boot and URLs go port-free (`https://course.localhost`). The CLI prints a hint when the port shows in the URL; nothing breaks if you ignore it.
- **Broken courses don't black-hole the app** — vite's dev server returns `200 + index.html` (SPA fallback) for missing files in `publicDir`, so a broken symlink (e.g. unmounted external drive at `~/Music/dj/dj-academy → /Volumes/My Passport/…`) makes `JSON.parse(lessons.json)` throw "Unexpected token '<'". `lessonsStore.loadLessons` checks `Content-Type` and treats non-JSON 200s as missing; `main.tsx` boot walks `courses.json` in order and skips courses that fail to load, so one missing drive doesn't crash the viewer.
- **Large courses live on the external drive** — both `dj-academy` and `producer-academy` are symlinks in `~/Music/dj/` pointing at `/Volumes/My Passport/DJ/<course>/`. Vite follows symlinks transparently; nothing in the app knows the difference. Mount the drive with `diskutil mount /dev/disk4s1` (or whatever `diskutil list external` shows for "My Passport") before starting the course viewer. On exFAT, filenames round-trip as NFD instead of APFS's NFC — `os.path.exists()` and vite's static serve both resolve NFC paths transparently, so lessons.json stored under NFC works either way. Caveat: rsync from APFS leaves AppleDouble `._*` sidecars all over the destination — harmless, just visual noise in `find` output.

### Set builder (`dj set build` + `dj-set-builder` skill)

- **Skill is the interactive layer; the CLI is a deterministic engine** — the `dj-set-builder` skill asks the user (name → mood → archetype → genres → duration → count → date), resolves answers to flags, then shells `dj set build`. The command never prompts; same flags → same set. This mirrors the course/vj/extension pattern (markdown skill drives a flag CLI). Build is **decoupled from export**: `dj set build` writes to `dj_sets`/`dj_set_tracks` and prints `set_id=<n>`; nothing pushes anywhere until `dj export set <id>` runs.
- **A set is an intensity curve, not a genre bucket** — each archetype (`ARCHETYPES` dict: `warmup, peak_time, late_night, closing, club_night, sunset, party, dark, festival, dinner, morning_coffee`) carries default genres + a BPM/energy window + a **multi-phase, non-monotonic** `Phase` curve (control points at `t∈[0,1]` with target intensity 1–10 + per-stem emphasis). `club_night` is the canonical shape: rise → bump → deliberate dip → S-climb → plateau → dip → higher plateau → final spike. To reshape, edit the `Phase` points — never hand-tune per-track energies. Default genres are overridable with `--genres` (the skill suggests include/exclude but the user's choice is final).
- **Composite intensity drives sequencing** — the curve targets `intensity = 10·(0.60·norm(mik_nrg) + 0.25·pct(bpm) + 0.15·drive)`, where `drive = mean(drums_pct, bass_pct)` and all `*_pct` are percentile ranks **within the candidate pool** (so "high energy for this set" is pool-relative, not absolute). Weights are constants (`W_NRG/W_BPM/W_DRIVE`). The greedy walk scores each next track by intensity-vs-curve + BPM smoothness + stem-emphasis match + Camelot-harmonic + vocal-clash + artist/label spacing; hard caps: max 2 tracks/artist, same-artist+title dedup, and the date-blend quotas below.
- **Date control is a proportional blend, not a single window** — `--date-blend` is a JSON list of `{label, from, to, ratio}` buckets; the set is filled so each bucket gets ~its ratio of the tracks (largest-remainder rounding, capped to pool supply, shortfall refilled into buckets with spare). One window is a single 100% bucket. Omitting `--date-blend` applies the default **75% ≤1yr / 12.5% 1–2yr / 12.5% older** mix. The skill converts free text ("may 2026 50%, jan 30%, feb 20%" / "last 2 years 80%, 2010-2020 20%") into this JSON; first matching bucket (list order) claims a track, so order narrowest-first on overlap.
- **Track-count bounds from duration** — `--count` is clamped to `[duration//5, duration//2]` (a track plays ~2–5 min); default `round(duration/3.5)`. `--list-archetypes` / `--list-genres` (with live pool counts) back the skill's suggestion step; `--json`/preview show the built set before `--save` persists it.
- **Storage: `record_built_set(name, archetype, ids, params)`** — `type` = the archetype key, so the same name can exist per archetype and **rebuilding the same name+archetype replaces it**. Build provenance (mood, duration, count, genres, date_blend, curve) is JSON in `dj_sets.params_json`, so a set is self-describing. Query by id with `db.get_set(id)` / `db.tracks_in_set_id(id)`; full edit ops (add/remove/move/reorder/rename/delete) live in `detect/db.py`. The engine lives in `helpers/build_set.py` (imported by `set/cli.py`); the CLI entry is `dj set build`.

### export (stored sets + SQL → destination)

- **All push targets live in `export/`** — `export.to_beatport` (`push_to_beatport` + `push_to_beatport_chart`) and `export.to_rekordbox` (`push_to_rekordbox`) are the single home for "write tracks to a destination". Two callers share them: `dj export beatport|rekordbox` (ad-hoc SQL curation) and `dj export set <id>` (stored set). `export/cli.py` owns all three verbs; `playlist/` now only owns `query.py` (SQL → rows), consumed by the export query verbs.
- **`dj export set <id> --to ...` is the only set→destination bridge** — `export.export_set.export_set(set_id, to)` resolves a stored set (`detect.db.get_set` + `tracks_in_set_id`, in set order), then dispatches: `bp_chart` → `push_to_beatport_chart` (publishable draft, description defaults from the set's mood/duration/archetype), `bp_playlist` → `push_to_beatport`, `rekordbox` → `fetch_full_rows` (via `playlist.query`) + `push_to_rekordbox`. The set builder (`helpers/build_set.py` / the `dj-set-builder` skill) stays decoupled: it only writes the set + returns the id; nothing exports until this command runs.
- **User SQL must return `beatport_id`** — `playlist.query.run_user_query` validates the query starts with `SELECT` (the only check; the column-shape error fires after fetch if `beatport_id` isn't in the result set). After exec, `fetch_full_rows` re-fetches via `enriched_tracks LEFT JOIN enriched_tracks_analysis USING(beatport_id)` so push code always has artist/title/genre/key/bpm/length_ms regardless of how the user wrote their SQL. The query runs with the connection's full DB privileges — this tool assumes the user owns the database.
- **No DJ Studio writes from this tool** — the previous `playlist dj-studio` destination wrote `projects-table/<uuid>` + `projects-meta-table/<uuid>` files, but DJ Studio also tracks per-mix UI state in IndexedDB (`~/Library/Application Support/DJ.Studio/IndexedDB/local-web_*.indexeddb.leveldb/`) that we couldn't write to — meaning UI delete was a no-op for tool-created mixes (the right-click → Delete flow looks up the IndexedDB row, doesn't find it, silently fails). We removed the destination rather than ship a half-working write path. DJ Studio is now read-only for this tool: we drive its SDK for analysis (`enrich analyse`) and read its library + projects-table for inspection only.
