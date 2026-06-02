"""Argparse CLI for `dj sync` — capture / enrich / playlist management.

  dj sync music [--playlist NAME | --library | --favorites]   capture Apple Music → sync_tracks
  dj sync music check-connections | list-playlists
  dj sync spotify ...                                         (capture: fast-follow; see TODOS.md)
  dj sync beatport [--playlist NAME]                          Beatport playlists → enriched_tracks
  dj sync <app> playlist list                                 list captured playlists + ids
  dj sync music|spotify playlist delete --all | --playlists
  dj sync beatport      playlist delete --all
  dj sync <app> playlist push --name NAME --ids ...|--query ...   recreate selection as an app playlist

`playlist delete` removes playlists from the SOURCE APP (Apple Music / Spotify /
Beatport), never from dj.db — your captured backup is always kept. It offers to sync
the latest first, then asks once before deleting. Scopes:
  * music    --playlists  all playlists incl. Favourite Songs (library kept)
             --all        the above + clears the Apple Music library
  * spotify  --playlists  all playlists (Liked Songs kept)
             --all        the above + clears Liked Songs
  * beatport --all        every Beatport playlist (no library/liked concept)
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

console = Console()

_TOKEN_HINT = (
    "Get fresh tokens:\n"
    "  1. Open beatport.com in a browser (logged in)\n"
    "  2. DevTools → Network → /api/auth/session → copy [bold]token.accessToken[/bold]\n"
    "     → set as BEATPORT_ACCESS_TOKEN in .env\n"
    "  3. DevTools → Application → Cookies → copy [bold]__Secure-next-auth.session-token[/bold]\n"
    "     → set as BEATPORT_SESSION_TOKEN in .env"
)

# App key (CLI verb) → sync_tracks.app value.
_APP_KEY = {"music": "apple_music", "spotify": "spotify"}


def _add_delete_scope_args(parser, app_key: str) -> None:
    """Scope + control flags for a music/spotify `playlist delete` parser.

    Two scopes (mutually exclusive): `--playlists` deletes the user playlists;
    `--all` additionally clears the app-wide collection (Apple Music library /
    Spotify Liked Songs). For Apple Music, "Favourite Songs" counts as a playlist,
    so both scopes remove it; only `--all` clears the library itself.
    """
    collection = "Liked Songs" if app_key == "spotify" else "library + Favourite Songs"
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", dest="scope_all", action="store_true",
                       help=f"Delete everything from {app_key}: all playlists AND {collection}.")
    scope.add_argument("--playlists", dest="scope_playlists", action="store_true",
                       help=("Delete all playlists" +
                             (" incl. Favourite Songs (library kept)." if app_key == "music"
                              else " (Liked Songs kept).")))
    parser.add_argument("--no-sync", dest="no_sync", action="store_true",
                        help="Skip the pre-delete sync (don't refresh the backup first).")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Sync + delete without interactive prompts.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be synced and deleted; change nothing.")


def _add_playlist_subcommands(parent_sub, app_key: str) -> None:
    """Attach `playlist list|delete|push` under a source parser (music/spotify)."""
    pl_p = parent_sub.add_parser("playlist", help="List, delete, or push captured playlists.")
    pl_sub = pl_p.add_subparsers(dest="pl_command")
    pl_sub.required = False
    pl_sub.add_parser("list", help="List captured playlists with their ids.")
    delete_p = pl_sub.add_parser(
        "delete", help="Delete playlists from the source app (backup in dj.db is kept).")
    _add_delete_scope_args(delete_p, app_key)
    push_p = pl_sub.add_parser("push", help="Create an app playlist from selected sync_tracks.")
    push_p.add_argument("--name", "-n", required=True, help="Target playlist name (new).")
    push_p.add_argument("--ids", help="Comma-separated sync_tracks ids to push.")
    push_p.add_argument("--query", "-q",
                        help="SQL selecting sync_tracks rows (must return app + native_track_id).")
    push_p.add_argument("--dry-run", action="store_true", help="Show what would be pushed.")
    push_p.add_argument("--verbose", "-v", action="store_true", help="List selected tracks.")


def add_sync_subparser(parent) -> argparse.ArgumentParser:
    sync_p = parent.add_parser("sync", help="Capture music platforms → enriched library.")
    sync_sub = sync_p.add_subparsers(dest="sync_command")
    sync_sub.required = False

    # ── music ─────────────────────────────────────────────────────────────────
    music_p = sync_sub.add_parser("music", help="Capture Apple Music playlists into sync_tracks.")
    music_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                         help="Capture only this Apple Music playlist (default: all).")
    music_p.add_argument("--library", dest="use_library", action="store_true",
                         help="Capture library songs (incremental via cursor).")
    music_p.add_argument("--favorites", dest="use_favorites", action="store_true",
                         help="Capture the 'Favourite Songs' playlist.")
    music_p.add_argument("--limit", type=int, default=0, metavar="N",
                         help="Stop after capturing N tracks (0 = no limit).")
    music_p.add_argument("--dry-run", action="store_true", help="Show what would be captured.")
    music_p.add_argument("--verbose", "-v", action="store_true", help="Per-playlist detail.")
    music_sub = music_p.add_subparsers(dest="music_command")
    music_sub.required = False
    music_sub.add_parser("check-connections", help="Verify MusicKit + Beatport credentials.")
    music_sub.add_parser("list-playlists", help="List Apple Music playlist names.")
    _add_playlist_subcommands(music_sub, "music")

    # ── spotify ─────────────────────────────────────────────────────────────────
    spotify_p = sync_sub.add_parser("spotify", help="Capture Spotify playlists into sync_tracks.")
    spotify_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                           help="Capture only this Spotify playlist (default: all).")
    spotify_p.add_argument("--library", dest="use_library", action="store_true",
                           help="Capture Liked Songs.")
    spotify_p.add_argument("--limit", type=int, default=0, metavar="N",
                           help="Stop after capturing N tracks (0 = no limit).")
    spotify_p.add_argument("--dry-run", action="store_true", help="Show what would be captured.")
    spotify_p.add_argument("--verbose", "-v", action="store_true", help="Per-playlist detail.")
    spotify_sub = spotify_p.add_subparsers(dest="spotify_command")
    spotify_sub.required = False
    _add_playlist_subcommands(spotify_sub, "spotify")

    # ── beatport ────────────────────────────────────────────────────────────────
    bp_p = sync_sub.add_parser("beatport", help="Sync Beatport playlists → enriched_tracks.")
    bp_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                      help="Sync only this Beatport playlist (default: all).")
    bp_p.add_argument("--limit", type=int, default=0, metavar="N", help="Stop after N new tracks.")
    bp_p.add_argument("--dry-run", action="store_true", help="Show what would be synced.")
    bp_p.add_argument("--verbose", "-v", action="store_true", help="Per-track detail.")
    bp_sub = bp_p.add_subparsers(dest="beatport_command")
    bp_sub.required = False
    bp_pl = bp_sub.add_parser("playlist", help="List or delete Beatport playlists.")
    bp_pl_sub = bp_pl.add_subparsers(dest="pl_command")
    bp_pl_sub.required = False
    bp_pl_sub.add_parser("list", help="List synced Beatport playlists with their ids.")
    bp_delete = bp_pl_sub.add_parser(
        "delete", help="Delete ALL playlists from the Beatport account (enriched_tracks kept).")
    bp_delete.add_argument("--all", dest="scope_all", action="store_true",
                           help="Delete every Beatport playlist (required).")
    bp_delete.add_argument("--no-sync", dest="no_sync", action="store_true",
                           help="Skip the pre-delete `sync beatport` (don't refresh the backup).")
    bp_delete.add_argument("--yes", "-y", action="store_true",
                           help="Sync + delete without interactive prompts.")
    bp_delete.add_argument("--dry-run", action="store_true",
                           help="Show what would be synced and deleted; change nothing.")
    bp_push = bp_pl_sub.add_parser("push", help="Create a Beatport playlist from selected tracks.")
    bp_push.add_argument("--name", "-n", required=True, help="Target Beatport playlist name (new or reused).")
    bp_push.add_argument("--ids", help="Comma-separated beatport_ids to push.")
    bp_push.add_argument("--query", "-q", help="SQL selecting rows (must return beatport_id).")
    bp_push.add_argument("--dry-run", action="store_true", help="Show what would be pushed.")
    bp_push.add_argument("--verbose", "-v", action="store_true", help="List selected tracks.")

    return sync_p


def _parse_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        console.print("[red]Error:[/red] --ids must be comma-separated integers.")
        sys.exit(1)


def _sync_app_playlist(app_key: str, args) -> None:
    """`playlist list/clear/push` for sync_tracks-backed sources (music/spotify)."""
    from sync import db as sync_db
    app = _APP_KEY[app_key]
    pl_command = getattr(args, "pl_command", None)

    if pl_command == "list":
        rows = sync_db.list_playlists(app)
        if not rows:
            console.print(f"[dim]No captured {app_key} playlists.[/dim]")
            return
        table = Table(title=f"Captured {app_key} playlists")
        table.add_column("native_playlist_id", overflow="fold")
        table.add_column("name")
        table.add_column("tracks", justify="right")
        for r in rows:
            table.add_row(str(r["native_playlist_id"]), r["playlist_name"] or "", str(r["track_count"]))
        console.print(table)
        return

    if pl_command == "delete":
        _delete_app_playlists(app_key, args)
        return

    if pl_command == "push":
        from sync.push import push_playlist
        push_playlist(
            app_key, args.name,
            query=args.query, ids=_parse_ids(args.ids),
            dry_run=args.dry_run, verbose=args.verbose,
        )
        return

    console.print(f"Usage: dj sync {app_key} playlist [list | delete --all|--playlists | "
                  "push --name NAME --ids ...|--query ...]")


# The app-wide collection captured as the `__library__` pseudo-playlist: Apple Music
# library / Spotify Liked Songs. It is NOT a user playlist, so it's excluded from the
# playlist set and only removed by `--all` (cleared in-app, never from dj.db).
_LIBRARY_PID = "__library__"


def _delete_app_playlists(app_key: str, args) -> None:
    """`playlist delete` for music/spotify — remove from the source app, keep dj.db.

    `--playlists` deletes the user playlists (Apple Music: incl. Favourite Songs);
    `--all` additionally clears the app-wide collection (library / Liked Songs).
    We only delete what we've captured, after offering to sync so the backup is
    current. dj.db is never touched — it's the permanent backup.
    """
    from rich.prompt import Confirm

    from sync import db as sync_db
    app = _APP_KEY[app_key]
    collection = "Liked Songs" if app_key == "spotify" else "library"
    captured = {r["native_playlist_id"]: r for r in sync_db.list_playlists(app)}

    if args.scope_all:
        clear_collection = True
    elif args.scope_playlists:
        clear_collection = False
    else:
        console.print("[red]Error:[/red] specify --all or --playlists.")
        sys.exit(1)

    # Playlist targets = every captured playlist except the library grouping. Apple
    # Music deletes by NAME (and "Favourite Songs" can appear under both its pseudo-id
    # and its real id, so dedup by name); Spotify unfollows by native playlist id.
    if app_key == "music":
        seen: set[str] = set()
        targets = []  # list[str] of playlist names
        for pid, row in captured.items():
            if pid == _LIBRARY_PID:
                continue
            name = row["playlist_name"] or pid
            if name not in seen:
                seen.add(name)
                targets.append(name)
        labels = targets
    else:
        targets = [(pid, captured[pid]["playlist_name"] or pid)  # list[(id, name)]
                   for pid in captured if pid != _LIBRARY_PID]
        labels = [name for _, name in targets]

    has_favourites = app_key == "music" and "Favourite Songs" in set(targets)

    parts = []
    if targets:
        parts.append(f"{len(targets)} playlist(s)")
    if clear_collection:
        parts.append(collection)
    if not parts:
        console.print(f"[yellow]Nothing captured to delete for {app_key}.[/yellow]")
        return

    console.print(f"[bold]Delete from {app_key}[/bold]: {' + '.join(parts)}")
    if labels:
        shown = ", ".join(labels[:30]) + (f" … (+{len(labels) - 30})" if len(labels) > 30 else "")
        console.print(f"[dim]  playlists: {shown}[/dim]")
    console.print(f"[dim]Removed from {app_key} only; your dj.db backup is kept.[/dim]")

    if args.dry_run:
        console.print("[yellow]DRY RUN[/yellow] — nothing synced or deleted.")
        return

    # 1) Sync first so the backup reflects the current state of what we're deleting.
    if not args.no_sync and (args.yes or Confirm.ask(
            f"Sync the latest from {app_key} first so your backup is current?", default=True)):
        _sync_before_delete(app_key, playlists=bool(targets),
                            favourites=has_favourites, collection=clear_collection)

    # 2) One confirmation for the whole (irreversible) operation.
    if not args.yes and not Confirm.ask(
            f"Delete the above from {app_key}? This can't be undone.", default=False):
        console.print("Aborted — nothing deleted.")
        return

    _execute_app_delete(app_key, targets, clear_collection, collection)
    console.print(f"[green]Done[/green] — deleted from {app_key} (dj.db backup kept).")


def _sync_before_delete(app_key: str, *, playlists: bool, favourites: bool, collection: bool) -> None:
    """Re-capture (back up) what's about to be deleted, before deleting it."""
    if app_key == "music":
        from sync.capture import run_sync_music
        if playlists:
            run_sync_music()
        if favourites:
            run_sync_music(use_favorites=True)
        if collection:
            run_sync_music(use_library=True)
    else:
        from sync.capture import run_sync_spotify
        if playlists:
            run_sync_spotify()
        if collection:
            run_sync_spotify(use_library=True)


def _execute_app_delete(app_key: str, targets, clear_collection: bool, collection: str) -> None:
    """Delete the playlists, then (if scoped) clear the app-wide collection."""
    if app_key == "music":
        from connections import musickit
        for name in targets:
            res = musickit.delete_apple_playlist(name)
            console.print(f"  [green]deleted[/green] {name}" if res["deleted"]
                          else f"  [yellow]not found in Apple Music[/yellow]: {name}")
        if clear_collection:
            console.print("Clearing Apple Music library…")
            n = musickit.clear_apple_library()
            console.print(f"  [green]cleared[/green] library — {n} track(s) removed")
        return

    from connections import spotify as sp
    try:
        client = sp.make_client()
    except sp.SpotifyAuthError as e:
        console.print(f"[red]Spotify auth:[/red] {e}")
        sys.exit(1)
    try:
        for pid, name in targets:
            client.unfollow_playlist(pid)
            console.print(f"  [green]deleted[/green] {name}")
        if clear_collection:
            console.print("Clearing Spotify Liked Songs…")
            n = client.clear_saved_tracks()
            console.print(f"  [green]cleared[/green] Liked Songs — {n} track(s) removed")
    finally:
        client.close()


def _beatport_playlist_ops(args) -> None:
    """`playlist delete/list/push` for Beatport (delete hits the real account)."""
    from detect import db as detect_db
    pl_command = getattr(args, "pl_command", None)

    if pl_command == "list":
        rows = detect_db.list_beatport_playlists()
        if not rows:
            console.print("[dim]No synced Beatport playlists.[/dim]")
            return
        table = Table(title="Synced Beatport playlists")
        table.add_column("beatport_id", justify="right")
        table.add_column("name")
        table.add_column("tracks", justify="right")
        for r in rows:
            table.add_row(str(r["beatport_id"]), r["name"] or "", str(r["track_count"]))
        console.print(table)
        return

    if pl_command == "delete":
        _delete_beatport_playlists(args)
        return

    if pl_command == "push":
        _beatport_playlist_push(args)
        return

    console.print("Usage: dj sync beatport playlist [list | delete --all | "
                  "push --name NAME --ids ...|--query ...]")


def _delete_beatport_playlists(args) -> None:
    """`beatport playlist delete --all` — delete EVERY real Beatport playlist, keep enriched_tracks.

    Targets are resolved live from the Beatport account (what actually exists to
    delete). Sync-first runs `dj sync beatport` per playlist so its tracks land in
    enriched_tracks before the playlist is removed. Beatport has no library/liked
    collection, so the only scope is `--all`.
    """
    from rich.prompt import Confirm

    from connections.beatport import make_bp_client

    if not args.scope_all:
        console.print("[red]Error:[/red] beatport delete requires --all.")
        sys.exit(1)

    beatport, client = make_bp_client()
    try:
        targets = [(int(pl["id"]), pl.get("name") or str(pl["id"]))
                   for pl in beatport.list_my_playlists()]
        if not targets:
            console.print("[yellow]No Beatport playlists to delete.[/yellow]")
            return

        console.print(f"[bold]Delete from Beatport[/bold]: {len(targets)} playlist(s)")
        shown = ", ".join(n for _, n in targets[:30]) + (
            f" … (+{len(targets) - 30})" if len(targets) > 30 else "")
        console.print(f"[dim]  playlists: {shown}[/dim]")
        console.print("[dim]Removed from Beatport only; enriched_tracks is kept.[/dim]")

        if args.dry_run:
            console.print("[yellow]DRY RUN[/yellow] — nothing synced or deleted.")
            return

        if not args.no_sync and (args.yes or Confirm.ask(
                "Sync each playlist into enriched_tracks first so your backup is current?",
                default=True)):
            from detect.sync_beatport import run_sync_beatport
            for _, name in targets:
                run_sync_beatport(dry_run=False, verbose=False, limit=0, playlist=name)

        if not args.yes and not Confirm.ask(
                f"Delete all {len(targets)} playlists from Beatport? This can't be undone.",
                default=False):
            console.print("Aborted — nothing deleted.")
            return

        deleted = 0
        for pid, name in targets:
            beatport.delete_playlist(pid)
            console.print(f"  [green]deleted[/green] {name}")
            deleted += 1
        console.print(f"[green]Done[/green] — deleted {deleted} playlist(s) from Beatport "
                      "(enriched_tracks kept).")
    finally:
        client.close()


def _beatport_playlist_push(args) -> None:
    """`beatport playlist push` — selected enriched_tracks → a Beatport playlist.

    The beatport analog of `dj sync music|spotify playlist push`: tracks are
    chosen by `--ids` (beatport_ids) or a `--query` returning a beatport_id
    column, then created as / merged into a named Beatport playlist. Wraps the
    shared `export.to_beatport.push_to_beatport` (same engine as `dj export
    beatport`).
    """
    from export.to_beatport import push_to_beatport
    from playlist.query import fetch_full_rows, run_user_query

    if args.ids:
        ids = _parse_ids(args.ids) or []
    elif args.query:
        try:
            ids = run_user_query(args.query)
        except ValueError as e:
            console.print(f"[red]Query error:[/red] {e}")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]SQL error:[/red] {e}")
            sys.exit(1)
    else:
        console.print("[red]Error:[/red] specify --ids or --query to choose tracks.")
        sys.exit(1)

    if not ids:
        console.print("[yellow]No tracks selected.[/yellow]")
        return

    if args.verbose:
        for row in fetch_full_rows(ids)[:20]:
            console.print(f"  [dim]{row.get('artist', '')} — {row.get('title', '')}[/dim]")
        if len(ids) > 20:
            console.print(f"  [dim]… and {len(ids) - 20} more[/dim]")

    push_to_beatport(ids, args.name, dry_run=args.dry_run, console=console)


def dispatch(args, sync_p: argparse.ArgumentParser) -> None:
    from connections import musickit
    from detect import db as detect_db
    from sync import db as sync_db

    # Bootstrap BOTH schemas: capture writes sync_tracks (sync.db); enrich writes
    # enriched_tracks (detect.db). detect.migrate() must run before any enrich.
    sync_db.init_db()
    detect_db.migrate()

    if not args.sync_command:
        sync_p.print_help()
        return

    # ── music ─────────────────────────────────────────────────────────────────
    if args.sync_command == "music":
        music_command = getattr(args, "music_command", None)

        if music_command == "check-connections":
            from connections.beatport import make_bp_client
            console.print("Checking MusicKit…", end=" ")
            authorized, msg = musickit.check_musickit()
            console.print("[green]OK[/green]" if authorized else f"[red]FAILED[/red]\n{msg}")
            console.print("Checking Beatport…", end=" ")
            try:
                beatport, client = make_bp_client()
                playlists = beatport.list_my_playlists()
                console.print(f"[green]OK[/green] ({len(playlists)} playlists found)")
                client.close()
            except SystemExit:
                raise
            except Exception as e:
                console.print(f"[red]FAILED[/red]\n{e}")
                if "401" in str(e):
                    console.print(f"\n[yellow]{_TOKEN_HINT}[/yellow]")
            return

        if music_command == "list-playlists":
            console.print("Fetching playlists from Apple Music…")
            try:
                names = musickit.list_playlists()
            except RuntimeError as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)
            for name in sorted(names):
                console.print(f"  {name}")
            console.print(f"\n[dim]{len(names)} playlists[/dim]")
            return

        if music_command == "playlist":
            _sync_app_playlist("music", args)
            return

        # No subcommand → capture.
        if args.use_library and args.use_favorites:
            console.print("[red]Error:[/red] --library and --favorites are mutually exclusive.")
            sys.exit(1)
        from sync.capture import run_sync_music
        run_sync_music(
            playlist=args.playlist,
            use_library=args.use_library,
            use_favorites=args.use_favorites,
            limit=args.limit,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        return

    # ── spotify ──────────────────────────────────────────────────────────────
    if args.sync_command == "spotify":
        spotify_command = getattr(args, "spotify_command", None)
        if spotify_command == "playlist":
            _sync_app_playlist("spotify", args)
            return
        from sync.capture import run_sync_spotify
        run_sync_spotify(
            playlist=args.playlist,
            use_library=args.use_library,
            limit=args.limit,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )
        return

    # ── beatport ────────────────────────────────────────────────────────────
    if args.sync_command == "beatport":
        beatport_command = getattr(args, "beatport_command", None)
        if beatport_command == "playlist":
            _beatport_playlist_ops(args)
            return
        from detect.sync_beatport import run_sync_beatport
        run_sync_beatport(
            dry_run=args.dry_run, verbose=args.verbose, limit=args.limit, playlist=args.playlist,
        )
        return
