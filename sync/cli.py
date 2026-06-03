"""Argparse CLI for `dj sync` — capture / enrich / playlist management.

  dj sync music [--playlist NAME | --library | --favorite-only]   capture Apple Music → sync_tracks
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
    push_p = pl_sub.add_parser(
        "push", help="Recreate app playlists from sync_tracks (ad-hoc selection or bulk restore).")
    push_p.add_argument("--name", "-n", help="Target playlist name (ad-hoc mode; with --ids/--query).")
    push_p.add_argument("--ids", help="Comma-separated sync_tracks ids to push.")
    push_p.add_argument("--query", "-q",
                        help="SQL selecting sync_tracks rows (must return app + native_track_id).")
    if app_key == "music":
        # Bulk restore from the dj.db backup (mirrors `playlist delete` scopes).
        push_p.add_argument("--all", dest="restore_all", action="store_true",
                            help="Restore everything: library + all playlists + favorites.")
        push_p.add_argument("--playlists", dest="restore_playlists", action="store_true",
                            help="Recreate every captured playlist (matches in-library tracks).")
        push_p.add_argument("--library", dest="restore_library", action="store_true",
                            help="Repopulate the library from captured __library__ rows (re-add).")
        push_p.add_argument("--favorite-only", dest="restore_favorites", action="store_true",
                            help="Restore favorites (re-mark loved). Combinable with --library.")
        push_p.add_argument("--readd-missing", dest="readd_missing", action="store_true",
                            help="Only act on tracks not already in the library; re-add them from "
                                 "the Apple Music catalog (best-effort; resumable).")
    elif app_key == "spotify":
        push_p.add_argument("--all", dest="restore_all", action="store_true",
                            help="Restore everything: Liked Songs + all playlists.")
        push_p.add_argument("--playlists", dest="restore_playlists", action="store_true",
                            help="Recreate every captured playlist (adds tracks by id).")
        push_p.add_argument("--library", dest="restore_library", action="store_true",
                            help="Re-save captured Liked Songs.")
    push_p.add_argument("--dry-run", action="store_true", help="Show what would be pushed.")
    push_p.add_argument("--verbose", "-v", action="store_true", help="List selected tracks.")


def add_sync_subparser(parent) -> argparse.ArgumentParser:
    sync_p = parent.add_parser("sync", help="Capture music platforms → enriched library.")
    sync_sub = sync_p.add_subparsers(dest="sync_command")
    sync_sub.required = False

    # ── music ─────────────────────────────────────────────────────────────────
    music_p = sync_sub.add_parser("music", help="Capture Apple Music playlists into sync_tracks.")
    music_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                         help="Capture only this Apple Music playlist (default: everything).")
    music_p.add_argument("--library", dest="use_library", action="store_true",
                         help="Capture only library songs (incremental via cursor).")
    music_p.add_argument("--favorites", "--favorite-only", dest="use_favorites", action="store_true",
                         help="Capture only the 'Favourite Songs' playlist (combinable with --library).")
    music_p.add_argument("--all", dest="sync_all", action="store_true",
                         help="Capture everything: all playlists + library + Favourite Songs (the default).")
    music_p.add_argument("--limit", type=int, default=0, metavar="N",
                         help="Stop after capturing N tracks (0 = no limit).")
    music_p.add_argument("--dry-run", action="store_true", help="Show what would be captured.")
    music_p.add_argument("--verbose", "-v", action="store_true", help="Per-playlist detail.")
    music_sub = music_p.add_subparsers(dest="music_command")
    music_sub.required = False
    _add_playlist_subcommands(music_sub, "music")

    # ── spotify ─────────────────────────────────────────────────────────────────
    spotify_p = sync_sub.add_parser("spotify", help="Capture Spotify playlists into sync_tracks.")
    spotify_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                           help="Capture only this Spotify playlist (default: everything).")
    spotify_p.add_argument("--library", dest="use_library", action="store_true",
                           help="Capture only Liked Songs.")
    spotify_p.add_argument("--all", dest="sync_all", action="store_true",
                           help="Capture everything: all playlists + Liked Songs (the default).")
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
    bp_p.add_argument("--all", dest="sync_all", action="store_true",
                      help="Sync all Beatport playlists (the default; for symmetry with music/spotify).")
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
    bp_push = bp_pl_sub.add_parser(
        "push", help="Create a Beatport playlist from selected tracks, or restore all (--all).")
    bp_push.add_argument("--name", "-n", help="Target Beatport playlist name (ad-hoc; with --ids/--query).")
    bp_push.add_argument("--ids", help="Comma-separated beatport_ids to push.")
    bp_push.add_argument("--query", "-q", help="SQL selecting rows (must return beatport_id).")
    # Bulk restore: recreate every captured Beatport playlist on the account. Beatport
    # has no library/liked concept, so --all and --playlists are equivalent.
    bp_push.add_argument("--all", dest="restore_all", action="store_true",
                         help="Recreate every captured Beatport playlist on the account.")
    bp_push.add_argument("--playlists", dest="restore_playlists", action="store_true",
                         help="Alias of --all (Beatport has only playlists).")
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
        scopes = _restore_scopes(args)
        if scopes:
            if app_key == "music":
                from sync.restore import restore_music
                restore_music(
                    scopes=scopes,
                    readd_missing=getattr(args, "readd_missing", False),
                    dry_run=args.dry_run, verbose=args.verbose,
                )
            else:  # spotify — library = Liked Songs, no favorites/re-add
                from sync.restore import restore_spotify
                restore_spotify(scopes=scopes, dry_run=args.dry_run, verbose=args.verbose)
            return
        if not args.name:
            console.print("[red]Error:[/red] ad-hoc push needs --name (with --ids/--query); "
                          "or use a bulk restore scope (--all/--playlists/--library/--favorite-only).")
            sys.exit(1)
        from sync.push import push_playlist
        push_playlist(
            app_key, args.name,
            query=args.query, ids=_parse_ids(args.ids),
            dry_run=args.dry_run, verbose=args.verbose,
        )
        return

    console.print(f"Usage: dj sync {app_key} playlist [list | delete --all|--playlists | "
                  "push --name NAME --ids ...|--query ... | "
                  "push --all|--playlists|--library|--favorite-only]")


def _restore_scopes(args) -> set[str]:
    """Resolve music bulk-restore scope flags into {'library','playlists','favorites'}."""
    if getattr(args, "restore_all", False):
        return {"library", "playlists", "favorites"}
    scopes = set()
    if getattr(args, "restore_library", False):
        scopes.add("library")
    if getattr(args, "restore_playlists", False):
        scopes.add("playlists")
    if getattr(args, "restore_favorites", False):
        scopes.add("favorites")
    return scopes


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
        if getattr(args, "restore_all", False) or getattr(args, "restore_playlists", False):
            from sync.restore import restore_beatport
            restore_beatport(dry_run=args.dry_run, verbose=args.verbose)
            return
        if not args.name:
            console.print("[red]Error:[/red] ad-hoc push needs --name (with --ids/--query); "
                          "or use --all to restore every captured Beatport playlist.")
            sys.exit(1)
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

        if music_command == "playlist":
            _sync_app_playlist("music", args)
            return

        # No subcommand → capture. --library + --favorite-only may combine; --all = all three.
        from sync.capture import run_sync_music
        run_sync_music(
            playlist=args.playlist,
            use_library=args.use_library,
            use_favorites=args.use_favorites,
            use_all=args.sync_all,
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
            use_all=args.sync_all,
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
        # Beatport has only playlists, so --all == the default (all playlists, no filter).
        run_sync_beatport(
            dry_run=args.dry_run, verbose=args.verbose, limit=args.limit,
            playlist=None if args.sync_all else args.playlist,
        )
        return
