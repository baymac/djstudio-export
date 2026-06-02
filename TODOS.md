# TODOS

## Verify the new sync integrations on real accounts/device
Both follow-ups below are implemented and unit-tested with mocked clients, but the
live external paths can't run in CI — verify once on the real machine:
- **Spotify capture/push** — needs a Spotify app (developer.spotify.com) with redirect
  URI `http://127.0.0.1:8888/callback` and `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`
  in `.env`. First `dj sync spotify` opens a browser to authorize; the refresh token is
  stored in `auth_cache`. Confirm the OAuth round-trip + that capture/push hit the account.
- **Apple Music push** — confirm `dj sync music playlist push` creates the playlist in
  Music.app and adds the matched tracks.

## Done (this PR)
- **`dj sync spotify` capture** — user-scoped OAuth client (`connections/spotify.py`),
  captures all playlists (or `--playlist`/`--library`) into `sync_tracks`.
- **`dj sync <app> playlist push`** — selects `sync_tracks` rows (`--ids` / `--query`) and
  recreates them as one playlist with `--name`. Spotify via Web API; Apple Music via
  AppleScript (Music.app), matching by name+artist.

## Known limitations
- **Apple Music push is library-scoped.** MusicKit's `createPlaylist` is unavailable on
  macOS, so push scripts Music.app and matches each track by exact name+artist within the
  local library. Tracks not in the library won't be added (fine for convert-back, since
  captured tracks came from the library). A non-exact title/artist won't match.
- **Spotify push** creates a private playlist owned by the authenticated user.
