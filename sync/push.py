"""`dj sync <app> playlist push` — convert-back: selected sync_tracks → one app playlist.

Pick rows from the faithful `sync_tracks` backup (by `--ids` or a `--query`) and
recreate them as a single named playlist in the source app:
  * apple_music → MusicKit bridge `--create-playlist` (creates a library playlist)
  * spotify     → Spotify Web API create-playlist + add-tracks (user OAuth)

This is the payoff of faithful capture: native track ids are stored per row, so the
push targets the exact tracks in the user's account.
"""
from __future__ import annotations

import sys

from rich.console import Console

from sync import db as sync_db

console = Console()

# CLI verb → sync_tracks.app value.
_APP_VALUE = {"music": "apple_music", "spotify": "spotify"}


def _resolve_rows(app_value: str, query: str | None, ids: list[int] | None) -> list[dict]:
    if ids:
        rows = sync_db.get_tracks_by_ids(ids)
    elif query:
        try:
            rows = sync_db.run_select(query)
        except ValueError as e:
            console.print(f"[red]Query error:[/red] {e}")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]SQL error:[/red] {e}")
            sys.exit(1)
    else:
        console.print("[red]Error:[/red] specify --ids or --query to choose tracks.")
        sys.exit(1)

    out: list[dict] = []
    for r in rows:
        keys = r.keys()
        if "app" not in keys or "native_track_id" not in keys:
            console.print("[red]Query error:[/red] result must include `app` and `native_track_id` "
                          "(select from sync_tracks).")
            sys.exit(1)
        if r["app"] == app_value and r["native_track_id"]:
            out.append({"native_track_id": r["native_track_id"],
                        "artist": r["artist"] if "artist" in keys else "",
                        "title": r["title"] if "title" in keys else "",
                        "album": r["album"] if "album" in keys else "",
                        "native_persistent_id": r["native_persistent_id"]
                        if "native_persistent_id" in keys else ""})
    return out


def push_playlist(
    app: str,
    name: str,
    *,
    query: str | None = None,
    ids: list[int] | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    app_value = _APP_VALUE[app]
    rows = _resolve_rows(app_value, query, ids)
    if not rows:
        console.print(f"[yellow]No {app} tracks selected (need rows with a native_track_id).[/yellow]")
        return

    console.print(f"[bold]Push → {app} playlist[/bold] \"{name}\"  ({len(rows)} tracks)")
    if verbose:
        for r in rows[:20]:
            console.print(f"  [dim]{r['artist']} — {r['title']}[/dim]")
        if len(rows) > 20:
            console.print(f"  [dim]… and {len(rows) - 20} more[/dim]")

    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no playlist created.")
        return

    if app == "music":
        _push_apple(name, rows)
    else:
        _push_spotify(name, [r["native_track_id"] for r in rows])


def _push_apple(name: str, rows: list[dict]) -> None:
    # macOS Music.app is scripted by name+artist (MusicKit can't create library
    # playlists on macOS); the tracks exist in the library since we captured them.
    from connections import musickit
    try:
        result = musickit.create_apple_playlist(name, rows)
    except RuntimeError as e:
        console.print(f"[red]Apple Music push failed:[/red] {e}")
        sys.exit(1)
    console.print(
        f"[green]Created[/green] Apple Music playlist \"{result.get('name', name)}\" "
        f"— added {result.get('added', 0)} of {result.get('requested', len(rows))} tracks."
    )


def _push_spotify(name: str, track_ids: list[str]) -> None:
    from connections import spotify as sp
    try:
        client = sp.make_client()
    except sp.SpotifyAuthError as e:
        console.print(f"[red]Spotify auth:[/red] {e}")
        sys.exit(1)
    try:
        user_id = client.current_user_id()
        playlist_id = client.create_playlist(user_id, name)
        added = client.add_tracks(playlist_id, track_ids)
        console.print(f"[green]Created[/green] Spotify playlist \"{name}\" — added {added} tracks.")
    finally:
        client.close()
