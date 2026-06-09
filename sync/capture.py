"""`dj sync music` — faithful capture of Apple Music playlists into `sync_tracks`.

No genre classification, no Beatport calls. Each playlist becomes a set of rows in
the flat `sync_tracks` table (one row per entry, ordered, duplicates preserved),
tagged with the playlist's stable id so it can be re-imported into the app later.
Enrichment is a separate step (`dj enrich metadata --sync`).
"""
from __future__ import annotations

import sys

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from connections import musickit
from sync import db as sync_db

console = Console()

APP = "apple_music"
SPOTIFY_APP = "spotify"
LIBRARY_PID = "__library__"
FAVORITES_PID = "__favorites__"
LIBRARY_CURSOR_KEY = "apple_music_library"


def run_sync_music(
    *,
    scope: str = "all",
    playlist: str | None = None,
    limit: int = 0,
    verbose: bool = False,
    dry_run: bool = False,
) -> None:
    """Capture Apple Music into sync_tracks. `scope` is one of:

      * "playlists" — all user playlists ONLY (Favourite Songs excluded).
      * "library"   — the library songs AND the Favourite Songs collection.
      * "all"       — both of the above (the default).

    A named `playlist` overrides scope to that one user playlist.
    """
    from paths import command_logger

    with command_logger("sync-music", console) as log_path:
        console.print(f"[dim]Log: {log_path}[/dim]")
        _run_sync_music_impl(
            scope=scope,
            playlist=playlist,
            limit=limit,
            verbose=verbose,
            dry_run=dry_run,
        )


def _run_sync_music_impl(
    *,
    scope: str,
    playlist: str | None,
    limit: int,
    verbose: bool,
    dry_run: bool,
) -> None:
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no changes will be made")

    do_playlists = bool(playlist) or scope in ("playlists", "all")
    do_library = not playlist and scope in ("library", "all")

    try:
        if do_playlists:
            _capture_all_playlists(playlist, limit, verbose, dry_run)
        if do_library:
            # "library" means the whole personal collection: loved Favourite Songs
            # + every library song.
            _capture_favorites(limit, verbose, dry_run)
            _capture_library(limit, verbose, dry_run)
    except RuntimeError as e:
        console.print(f"[red]MusicKit error:[/red] {e}")
        sys.exit(1)


def _attach_persistent_ids(playlist_name: str, rows: list[dict]) -> None:
    """Tag each captured row with its Apple Music library persistent id, for exact restore.

    MusicKit gives no persistent id, so we read it from Music.app via AppleScript
    (`musickit.read_playlist_persistent_ids`) and align position-by-position with the
    MusicKit rows. To never attach a WRONG id, we only apply when the two enumerations
    agree exactly — same length AND same track name at every position. Any mismatch,
    ambiguity (duplicate playlist name), or read error leaves persistent ids unset, so
    restore falls back to name+artist+album. Best-effort: failure here never aborts capture.
    """
    try:
        pairs = musickit.read_playlist_persistent_ids(playlist_name)
    except Exception:  # noqa: BLE001 — capture must survive an AppleScript hiccup
        return
    if pairs is None or len(pairs) != len(rows):
        return

    def norm(s: str | None) -> str:
        return (s or "").strip().casefold()

    if any(norm(name) != norm(row.get("title")) for (_, name), row in zip(pairs, rows)):
        return  # order/content drift between the two reads — don't risk wrong ids
    for (pid, _), row in zip(pairs, rows):
        row["native_persistent_id"] = pid


def _capture_all_playlists(playlist: str | None, limit: int, verbose: bool, dry_run: bool) -> None:
    label = f'playlist "{playlist}"' if playlist else "all Apple Music playlists"
    console.print(f"Capturing [bold]{label}[/bold] from Apple Music…")

    # native_playlist_id → {"name": str, "rows": [row, …]}
    groups: dict[str, dict] = {}
    seen_rows = 0
    for rec in musickit.stream_all_playlists():
        pl_name = rec.get("playlist_name") or ""
        if playlist and pl_name != playlist:
            continue
        npid = rec.get("native_playlist_id") or pl_name
        g = groups.setdefault(npid, {"name": pl_name, "rows": []})
        g["rows"].append({
            "native_track_id": rec.get("native_track_id"),
            "native_url": rec.get("url"),
            "artist": rec.get("artist"),
            "title": rec.get("name"),
            "album": rec.get("album"),
            "playlist_name": pl_name,
            "position": rec.get("position"),
        })
        seen_rows += 1
        if limit and seen_rows >= limit:
            break

    if not groups:
        console.print("[dim]No matching playlists captured.[/dim]")
        return

    console.print(f"Found [bold]{len(groups)}[/bold] playlists")

    total = 0
    total_new = total_skipped = total_removed = 0

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        for npid, g in groups.items():
            name = g["name"]
            rows = g["rows"]
            task = progress.add_task(f"[cyan]{name}[/cyan]", total=None)
            _attach_persistent_ids(name, rows)
            progress.update(task, total=len(rows), completed=len(rows))

            if dry_run:
                progress.update(task, description=f"[cyan]{name}[/cyan]  {len(rows)} tracks (dry run)")
                total += len(rows)
                continue

            stats = sync_db.replace_playlist(APP, npid, rows)
            total_new += stats["new"]
            total_skipped += stats["kept"]
            total_removed += stats["removed"]
            total += stats["total"]
            removed_part = f", {stats['removed']} removed" if stats["removed"] else ""
            progress.update(
                task,
                description=f"[cyan]{name}[/cyan]  +{stats['new']} new, {stats['kept']} skipped{removed_part}",
            )

    console.print()
    console.print(f"[bold]Capture {'(dry run) ' if dry_run else ''}complete[/bold]")
    console.print(f"  Playlists: {len(groups)}")
    if dry_run:
        console.print(f"  Tracks:    {total}")
    else:
        console.print(f"  New:       {total_new}")
        console.print(f"  Skipped:   {total_skipped}")
        if total_removed:
            console.print(f"  Removed:   {total_removed}")


def _capture_favorites(limit: int, verbose: bool, dry_run: bool) -> None:
    console.print("Capturing [bold]Favourite Songs[/bold] from Apple Music…")
    rows = []
    seen: set[str] = set()
    dupes = 0
    for rec in musickit.stream_favorite_tracks():
        # Favourite Songs is a loved-SET — a track loved twice carries no meaning,
        # so collapse repeats here (unlike user playlists, where a repeated track
        # can be intentional and replace_playlist preserves it). Reuse the DB's own
        # identity function so this collapse and replace_playlist agree on what "the
        # same track" is (and a pipe/space in artist or title can't false-collide).
        cat = rec.get("catalog_id")
        key = sync_db._dedup_key(cat, rec.get("artist"), rec.get("name"))
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        rows.append({
            "native_track_id": cat,
            "native_url": rec.get("url"),
            "artist": rec.get("artist"),
            "title": rec.get("name"),
            "album": rec.get("album"),
            "playlist_name": "Favourite Songs",
            "position": len(rows),
        })
        if limit and len(rows) >= limit:
            break

    if dry_run:
        console.print(f"  [dim]would capture[/dim] Favourite Songs: {len(rows)} tracks")
        return
    stats = sync_db.replace_playlist(APP, FAVORITES_PID, rows)
    removed_part = f", {stats['removed']} removed" if stats["removed"] else ""
    dupes_part = f", {dupes} duplicate{'s' if dupes != 1 else ''} collapsed" if dupes else ""
    console.print(
        f"[bold]Capture complete[/bold] — Favourite Songs: {stats['total']} tracks "
        f"([green]+{stats['new']} new[/green], {stats['kept']} skipped{removed_part}{dupes_part})"
    )


def run_sync_spotify(
    *,
    scope: str = "all",
    playlist: str | None = None,
    limit: int = 0,
    verbose: bool = False,
    dry_run: bool = False,
) -> None:
    """Faithful capture of the user's Spotify playlists/library into sync_tracks.

    `scope` is one of "playlists" (all playlists, Liked Songs excluded),
    "library" (Liked Songs only), or "all" (both, the default). A named
    `playlist` overrides scope to that one playlist.
    """
    from paths import command_logger

    with command_logger("sync-spotify", console) as log_path:
        console.print(f"[dim]Log: {log_path}[/dim]")
        _run_sync_spotify_impl(
            scope=scope,
            playlist=playlist,
            limit=limit,
            verbose=verbose,
            dry_run=dry_run,
        )


def _run_sync_spotify_impl(
    *,
    scope: str,
    playlist: str | None,
    limit: int,
    verbose: bool,
    dry_run: bool,
) -> None:
    from connections import spotify as sp

    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no changes will be made")

    try:
        client = sp.make_client()
    except sp.SpotifyAuthError as e:
        console.print(f"[red]Spotify auth:[/red] {e}")
        sys.exit(1)

    try:
        # Build the list of capture targets: (native_playlist_id, name, fetch_fn).
        # Liked Songs is modelled as a single pseudo-playlist so the logging path
        # is identical to the per-playlist one. No scope given → capture EVERYTHING
        # (playlists + Liked Songs); --library = Liked Songs only; --playlist narrows.
        do_playlists = bool(playlist) or scope in ("playlists", "all")
        do_library = not playlist and scope in ("library", "all")
        targets = []
        if do_playlists:
            console.print("Fetching Spotify playlists…")
            playlists = client.list_my_playlists()
            if playlist:
                playlists = [p for p in playlists if p["name"] == playlist]
            if playlist:
                console.print(f'Syncing playlist [bold]"{playlist}"[/bold]')
            else:
                console.print(f"Found [bold]{len(playlists)}[/bold] playlists")
            targets += [
                (pl["id"], pl["name"], (lambda pid=pl["id"]: client.playlist_tracks(pid)))
                for pl in playlists
            ]
        if do_library:
            console.print("Fetching Spotify Liked Songs…")
            targets.append((LIBRARY_PID, "Liked Songs", client.saved_tracks))
        if not targets:
            console.print("[dim]Nothing to capture.[/dim]")
            return

        total_new = total_skipped = total_removed = 0
        inaccessible = 0
        captured_tracks = 0

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        )

        with progress:
            for npid, name, fetch in targets:
                task = progress.add_task(f"[cyan]{name}[/cyan]", total=None)
                try:
                    rows = fetch()
                except httpx.HTTPStatusError as e:
                    code = e.response.status_code
                    # Spotify returns 404 on the tracks endpoint for its own
                    # algorithmic/editorial playlists (Discover Weekly, Release
                    # Radar, Daily Mix, …) — they appear in me/playlists but aren't
                    # fetchable by third-party apps. Skip, don't abort the run.
                    if code == 404:
                        progress.update(task, total=1, completed=1,
                                        description=f"[yellow]{name}[/yellow]  inaccessible (Spotify-owned)")
                        inaccessible += 1
                        continue
                    progress.update(task, description=f"[red]{name}[/red]  HTTP {code}")
                    progress.log(f"[red]error[/red] {name} ({npid}): HTTP {code} — {e}")
                    raise

                for r in rows:
                    r["playlist_name"] = name
                if limit:
                    rows = rows[:limit]
                progress.update(task, total=len(rows), completed=len(rows))

                if dry_run:
                    progress.update(task, description=f"[cyan]{name}[/cyan]  {len(rows)} tracks (dry run)")
                    captured_tracks += len(rows)
                    continue

                stats = sync_db.replace_playlist(SPOTIFY_APP, npid, rows)
                total_new += stats["new"]
                total_skipped += stats["kept"]
                total_removed += stats["removed"]
                captured_tracks += stats["total"]
                removed_part = f", {stats['removed']} removed" if stats["removed"] else ""
                progress.update(
                    task,
                    description=f"[cyan]{name}[/cyan]  +{stats['new']} new, {stats['kept']} skipped{removed_part}",
                )

        console.print()
        console.print(f"[bold]Capture {'(dry run) ' if dry_run else ''}complete[/bold]")
        if dry_run:
            console.print(f"  Tracks:        {captured_tracks}")
        else:
            console.print(f"  New:           {total_new}")
            console.print(f"  Skipped:       {total_skipped}")
            if total_removed:
                console.print(f"  Removed:       {total_removed}")
        if inaccessible:
            console.print(f"  [dim]Inaccessible:  {inaccessible} Spotify-owned playlist(s)[/dim]")
    finally:
        client.close()


def _capture_library(limit: int, verbose: bool, dry_run: bool) -> None:
    console.print("Capturing [bold]library songs[/bold] from Apple Music…")
    cursor = sync_db.get_cursor(LIBRARY_CURSOR_KEY)
    if cursor:
        console.print(f"[dim]Library cursor: {cursor} — only newer additions[/dim]")

    tracks = list(musickit.stream_library_tracks())
    # Sort ascending so the cursor advances cleanly even on a partial run.
    tracks.sort(key=lambda t: t.get("library_added_date") or "")
    if cursor:
        tracks = [t for t in tracks if (t.get("library_added_date") or "") > cursor]
    if limit:
        tracks = tracks[:limit]

    if not tracks:
        console.print("[dim]No new library songs since last capture.[/dim]")
        return

    if dry_run:
        console.print(f"  [dim]would capture[/dim] library: {len(tracks)} new tracks")
        return

    for t in tracks:
        sync_db.insert_sync_track(
            APP,
            native_track_id=t.get("catalog_id"),
            native_url=t.get("url"),
            artist=t.get("artist"),
            title=t.get("name"),
            album=t.get("album"),
            playlist_name="Library",
            native_playlist_id=LIBRARY_PID,
            position=None,
        )

    max_date = max((t.get("library_added_date") or "" for t in tracks), default="")
    if max_date:
        sync_db.set_cursor(LIBRARY_CURSOR_KEY, max_date)
        console.print(f"[dim]Library cursor advanced to {max_date}[/dim]")
    console.print(f"[bold]Capture complete[/bold] — library: {len(tracks)} new tracks")
