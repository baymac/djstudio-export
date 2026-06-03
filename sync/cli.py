"""Argparse CLI for `dj sync` — capture / restore / delete source-app playlists.

Every source app (Apple Music / Spotify / Beatport) exposes the same four verbs:

    dj sync <app> pull   [--playlists | --library | --all] [--playlist NAME]
    dj sync <app> list
    dj sync <app> push   [--playlists | --library | --all] | [--name NAME --ids/--query]
    dj sync <app> delete [--playlists | --library | --all]

The scope flags mean the SAME thing for every verb:

  * --playlists  all user playlists.  (Apple Music: EXCLUDES Favourite Songs;
                 Spotify: EXCLUDES Liked Songs.)
  * --library    the personal collection.  (Apple Music: library songs +
                 Favourite Songs; Spotify: Liked Songs.)
  * --all        --playlists + --library.  (Beatport: the ONLY scope — it has no
                 library/liked concept, so --all == every Beatport playlist.)

`pull` backs the source app up INTO dj.db (default scope: --all). `push` restores
FROM the dj.db backup back into the source app, or pushes an ad-hoc --ids/--query
selection to a named playlist. `delete` removes from the SOURCE APP only — dj.db is
never touched, and delete offers to `pull` first so the backup is current.
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

console = Console()

# App key (CLI verb) → sync_tracks.app value.
_APP_KEY = {"music": "apple_music", "spotify": "spotify"}

# Pseudo "playlists" that model an app-wide collection, never a user playlist:
# Apple Music library / Favourite Songs, Spotify Liked Songs. Excluded from the
# playlist set; handled by the --library / --all scopes instead.
_LIBRARY_PIDS = {"__library__", "__favorites__"}


# ── parser construction ──────────────────────────────────────────────────────

def _scope_help(app_key: str) -> dict[str, str]:
    if app_key == "music":
        return {
            "playlists": "All user playlists (excludes Favourite Songs).",
            "library": "Library songs + Favourite Songs.",
            "all": "Everything: all playlists + library + Favourite Songs.",
        }
    if app_key == "spotify":
        return {
            "playlists": "All playlists (excludes Liked Songs).",
            "library": "Liked Songs.",
            "all": "Everything: all playlists + Liked Songs.",
        }
    return {"all": "Every Beatport playlist (Beatport has no library/liked concept)."}


def _add_scope_flags(parser, app_key: str, *, required: bool, default: str | None) -> None:
    """Add the shared --playlists/--library/--all scope group → dest='scope'.

    Beatport only gets --all. `required` forces the user to pick (used by delete);
    `default` is the scope when none is given (e.g. pull defaults to 'all').
    """
    helps = _scope_help(app_key)
    g = parser.add_mutually_exclusive_group(required=required)
    if app_key == "beatport":
        g.add_argument("--all", dest="scope", action="store_const", const="all", help=helps["all"])
    else:
        g.add_argument("--playlists", dest="scope", action="store_const", const="playlists",
                       help=helps["playlists"])
        g.add_argument("--library", dest="scope", action="store_const", const="library",
                       help=helps["library"])
        g.add_argument("--all", dest="scope", action="store_const", const="all", help=helps["all"])
    parser.set_defaults(scope=default)


def _add_app_commands(sync_sub, app_key: str, app_help: str) -> None:
    """Attach `pull | list | push | delete` under one source app parser."""
    app_p = sync_sub.add_parser(app_key, help=app_help)
    op_sub = app_p.add_subparsers(dest="op")
    op_sub.required = False

    # ── pull (capture → dj.db backup) ───────────────────────────────────────
    pull_p = op_sub.add_parser("pull", help="Capture from the source app into dj.db (default: --all).")
    _add_scope_flags(pull_p, app_key, required=False, default="all")
    pull_p.add_argument("--playlist", "-p", default=None, metavar="NAME",
                        help="Capture only this one playlist (overrides scope).")
    pull_p.add_argument("--limit", type=int, default=0, metavar="N",
                        help="Stop after capturing N tracks (0 = no limit).")
    pull_p.add_argument("--dry-run", action="store_true", help="Show what would be captured.")
    pull_p.add_argument("--verbose", "-v", action="store_true", help="Per-playlist detail.")

    # ── list ────────────────────────────────────────────────────────────────
    op_sub.add_parser("list", help="List captured playlists with their ids.")

    # ── push (restore from dj.db, or ad-hoc selection) ──────────────────────
    push_p = op_sub.add_parser(
        "push", help="Restore from the dj.db backup to the source app, or push an ad-hoc selection.")
    _add_scope_flags(push_p, app_key, required=False, default=None)
    push_p.add_argument("--name", "-n", help="Ad-hoc: target playlist name (with --ids/--query).")
    push_p.add_argument("--ids", help="Ad-hoc: comma-separated sync_tracks/beatport ids to push.")
    push_p.add_argument("--query", "-q", help="Ad-hoc: SQL selecting rows to push.")
    if app_key == "music":
        push_p.add_argument("--readd-missing", dest="readd_missing", action="store_true",
                            help="Only act on tracks not already in the library; re-add them from "
                                 "the Apple Music catalog (best-effort; resumable).")
    push_p.add_argument("--dry-run", action="store_true", help="Show what would be pushed.")
    push_p.add_argument("--verbose", "-v", action="store_true", help="List selected tracks.")

    # ── delete (from the source app; dj.db backup kept) ─────────────────────
    del_p = op_sub.add_parser(
        "delete", help="Delete from the source app (the dj.db backup is always kept).")
    _add_scope_flags(del_p, app_key, required=True, default=None)
    del_p.add_argument("--no-sync", dest="no_sync", action="store_true",
                       help="Skip the pre-delete pull (don't refresh the backup first).")
    del_p.add_argument("--yes", "-y", action="store_true",
                       help="Pull + delete without interactive prompts.")
    del_p.add_argument("--dry-run", action="store_true",
                       help="Show what would be pulled and deleted; change nothing.")


def add_sync_subparser(parent) -> argparse.ArgumentParser:
    sync_p = parent.add_parser("sync", help="Capture / restore / delete source-app playlists.")
    sync_sub = sync_p.add_subparsers(dest="sync_command")
    sync_sub.required = False
    _add_app_commands(sync_sub, "music", "Apple Music playlists ↔ dj.db.")
    _add_app_commands(sync_sub, "spotify", "Spotify playlists ↔ dj.db.")
    _add_app_commands(sync_sub, "beatport", "Beatport playlists ↔ dj.db / enriched_tracks.")
    return sync_p


def _parse_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        console.print("[red]Error:[/red] --ids must be comma-separated integers.")
        sys.exit(1)


# ── dispatch ─────────────────────────────────────────────────────────────────

def dispatch(args, sync_p: argparse.ArgumentParser) -> None:
    from detect import db as detect_db
    from sync import db as sync_db

    # Bootstrap BOTH schemas: capture writes sync_tracks (sync.db); enrich writes
    # enriched_tracks (detect.db). detect.migrate() must run before any enrich.
    sync_db.init_db()
    detect_db.migrate()

    app_key = args.sync_command
    if not app_key:
        sync_p.print_help()
        return

    op = getattr(args, "op", None)
    if not op:
        console.print(f"Usage: dj sync {app_key} [pull | list | push | delete] …")
        return

    if op == "pull":
        _do_pull(app_key, args)
    elif op == "list":
        _do_list(app_key)
    elif op == "push":
        _do_push(app_key, args)
    elif op == "delete":
        _do_delete(app_key, args)


def _do_pull(app_key: str, args) -> None:
    if app_key == "music":
        from sync.capture import run_sync_music
        run_sync_music(scope=args.scope, playlist=args.playlist,
                       limit=args.limit, verbose=args.verbose, dry_run=args.dry_run)
    elif app_key == "spotify":
        from sync.capture import run_sync_spotify
        run_sync_spotify(scope=args.scope, playlist=args.playlist,
                         limit=args.limit, verbose=args.verbose, dry_run=args.dry_run)
    else:  # beatport — only --all (its single scope); a named --playlist narrows it.
        from detect.sync_beatport import run_sync_beatport
        # playlist=None means "all playlists" (what --all asks for); a named --playlist wins.
        run_sync_beatport(dry_run=args.dry_run, verbose=args.verbose, limit=args.limit,
                          playlist=args.playlist)


def _do_list(app_key: str) -> None:
    if app_key == "beatport":
        from detect import db as detect_db
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

    from sync import db as sync_db
    app = _APP_KEY[app_key]
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


# ── push / restore ───────────────────────────────────────────────────────────

def _restore_scopes(app_key: str, scope: str) -> set[str]:
    """Map a single CLI scope → the restore.py scope set for this app.

    restore_music understands {'library','playlists','favorites'}; restore_spotify
    understands {'library','playlists'}. The --library scope means the whole
    personal collection, so for Apple Music it covers BOTH library and favorites.
    """
    if app_key == "music":
        return {
            "playlists": {"playlists"},
            "library": {"library", "favorites"},
            "all": {"playlists", "library", "favorites"},
        }[scope]
    if app_key == "spotify":
        return {
            "playlists": {"playlists"},
            "library": {"library"},
            "all": {"playlists", "library"},
        }[scope]
    return {"all"}  # beatport


def _do_push(app_key: str, args) -> None:
    scope = getattr(args, "scope", None)

    if app_key == "beatport":
        if scope:  # only --all exists for Beatport
            from sync.restore import restore_beatport
            restore_beatport(dry_run=args.dry_run, verbose=args.verbose)
            return
        if not args.name:
            console.print("[red]Error:[/red] ad-hoc push needs --name (with --ids/--query); "
                          "or use --all to restore every captured Beatport playlist.")
            sys.exit(1)
        _beatport_playlist_push(args)
        return

    if scope:
        scopes = _restore_scopes(app_key, scope)
        if app_key == "music":
            from sync.restore import restore_music
            restore_music(scopes=scopes, readd_missing=getattr(args, "readd_missing", False),
                          dry_run=args.dry_run, verbose=args.verbose)
        else:
            from sync.restore import restore_spotify
            restore_spotify(scopes=scopes, dry_run=args.dry_run, verbose=args.verbose)
        return

    if not args.name:
        console.print("[red]Error:[/red] push needs a scope (--all/--playlists/--library) for a bulk "
                      "restore, or --name with --ids/--query for an ad-hoc playlist.")
        sys.exit(1)
    from sync.push import push_playlist
    push_playlist(app_key, args.name, query=args.query, ids=_parse_ids(args.ids),
                  dry_run=args.dry_run, verbose=args.verbose)


# ── delete (from the source app) ─────────────────────────────────────────────

def _do_delete(app_key: str, args) -> None:
    if app_key == "beatport":
        _delete_beatport_playlists(args)
        return
    _delete_app_playlists(app_key, args)


def _playlist_delete_targets(app_key: str, captured: dict):
    """Resolve which captured playlists are deletable user playlists.

    Excludes the app-wide collections (__library__/__favorites__) and, for Apple
    Music, the "Favourite Songs" playlist by name — those belong to the --library
    scope. Apple Music deletes by NAME (deduped, since duplicate names are legal);
    Spotify unfollows by native playlist id.
    """
    if app_key == "music":
        seen: set[str] = set()
        targets: list[str] = []
        for pid, row in captured.items():
            if pid in _LIBRARY_PIDS:
                continue
            name = row["playlist_name"] or pid
            if name == "Favourite Songs":  # belongs to --library, not --playlists
                continue
            if name not in seen:
                seen.add(name)
                targets.append(name)
        return targets, list(targets)
    targets = [(pid, captured[pid]["playlist_name"] or pid)
               for pid in captured if pid not in _LIBRARY_PIDS]
    return targets, [name for _, name in targets]


def _live_playlist_keys(app_key: str) -> set | None:
    """Live identity of every playlist that currently exists in the source app.

    Apple Music → set of playlist NAMES (delete matches by name); Spotify → set of
    playlist IDS (unfollow targets by id). Returns None on any read/auth error so the
    caller keeps all captured targets rather than silently skipping a real delete.
    """
    if app_key == "music":
        from connections import musickit
        names = musickit.read_live_playlist_names()
        return names or None  # empty == AppleScript error → fall back to all
    if app_key == "spotify":
        from connections import spotify as sp
        try:
            client = sp.make_client()
        except sp.SpotifyAuthError:
            return None
        try:
            ids = {p["id"] for p in client.list_my_playlists()}
        except Exception:  # noqa: BLE001 — any fetch failure → keep all targets
            return None
        finally:
            client.close()
        return ids or None  # empty /me/playlists is itself suspicious → fall back to all
    return None


def _filter_targets_to_live(app_key: str, targets, labels):
    """Drop delete targets that no longer exist in the source app. Returns (targets, labels).

    Apple Music targets are names (list[str]); Spotify targets are (id, name) tuples.
    The live key is the name for music, the id for Spotify.

    Two fail-safes keep this from silently refusing a real delete: a None live set
    (read/auth error, or empty result) passes every target through; and if the filter
    would drop EVERY target — a strong sign the live read is untrustworthy (wrong
    account, partial page, scope gap) rather than "you already deleted all 76" — we
    keep them all and warn. The underlying deletes are themselves safe to re-attempt
    (Spotify unfollow is idempotent; Apple Music reports "not found").
    """
    live = _live_playlist_keys(app_key)
    if live is None:
        return targets, labels
    if app_key == "music":
        kept = [name for name in targets if name in live]
        kept_labels = list(kept)
    else:
        kept = [(pid, name) for (pid, name) in targets if pid in live]
        kept_labels = [name for _, name in kept]
    skipped = len(targets) - len(kept)
    if skipped and not kept:
        where = "Apple Music" if app_key == "music" else "Spotify"
        console.print(
            f"[yellow]The live {where} playlist list matched none of the "
            f"{len(targets)} captured playlists — keeping them all rather than "
            "skipping every delete. (Check you're signed into the same account.)[/yellow]"
        )
        return targets, labels
    if skipped:
        where = "Apple Music" if app_key == "music" else "Spotify"
        console.print(f"[dim]Skipping {skipped} playlist(s) already gone from {where}.[/dim]")
    return kept, kept_labels


def _delete_app_playlists(app_key: str, args) -> None:
    """`<music|spotify> delete` — remove from the source app, keep dj.db.

    Scope (same meaning as pull/push): --playlists deletes the user playlists;
    --library clears the personal collection (Apple Music library + Favourite
    Songs / Spotify Liked Songs); --all does both. We only delete what we've
    captured, after offering to pull so the backup is current. dj.db is never
    touched — it's the permanent backup.
    """
    from rich.prompt import Confirm

    from sync import db as sync_db
    app = _APP_KEY[app_key]
    scope = args.scope  # required → always 'playlists' | 'library' | 'all'
    collection = "Liked Songs" if app_key == "spotify" else "library + Favourite Songs"
    captured = {r["native_playlist_id"]: r for r in sync_db.list_playlists(app)}

    do_playlists = scope in ("playlists", "all")
    do_collection = scope in ("library", "all")

    targets, labels = _playlist_delete_targets(app_key, captured) if do_playlists else ([], [])

    # The dj.db backup is permanent, so a playlist deleted in a prior run still sits
    # in `captured` and would resurface here ("not found in Apple Music" / a no-op
    # Spotify unfollow). Drop the ones that no longer exist in the source app (live
    # read). On any error the live set is None → keep all targets (no silent skips).
    if do_playlists and targets:
        targets, labels = _filter_targets_to_live(app_key, targets, labels)

    parts = []
    if targets:
        parts.append(f"{len(targets)} playlist(s)")
    if do_collection:
        parts.append(collection)
    if not parts:
        console.print(f"[yellow]Nothing captured to delete for {app_key} (scope: {scope}).[/yellow]")
        return

    console.print(f"[bold]Delete from {app_key}[/bold]: {' + '.join(parts)}")
    if labels:
        shown = ", ".join(labels[:30]) + (f" … (+{len(labels) - 30})" if len(labels) > 30 else "")
        console.print(f"[dim]  playlists: {shown}[/dim]")
    console.print(f"[dim]Removed from {app_key} only; your dj.db backup is kept.[/dim]")

    if args.dry_run:
        console.print("[yellow]DRY RUN[/yellow] — nothing pulled or deleted.")
        return

    # 1) Pull first so the backup reflects the current state of what we're deleting.
    if not args.no_sync and (args.yes or Confirm.ask(
            f"Pull the latest from {app_key} first so your backup is current?", default=True)):
        _sync_before_delete(app_key, scope)

    # 2) One confirmation for the whole (irreversible) operation.
    if not args.yes and not Confirm.ask(
            f"Delete the above from {app_key}? This can't be undone.", default=False):
        console.print("Aborted — nothing deleted.")
        return

    _execute_app_delete(app_key, targets, do_collection, collection)
    console.print(f"[green]Done[/green] — deleted from {app_key} (dj.db backup kept).")


def _sync_before_delete(app_key: str, scope: str) -> None:
    """Re-capture (back up) EXACTLY the scope about to be deleted, before deleting it.

    One call into the same `pull` entrypoint, with the same scope — so the backup
    log is identical to a real `dj sync <app> pull` and we never re-capture a
    collection that isn't being removed.
    """
    if app_key == "music":
        from sync.capture import run_sync_music
        run_sync_music(scope=scope)
    else:
        from sync.capture import run_sync_spotify
        run_sync_spotify(scope=scope)


def _execute_app_delete(app_key: str, targets, do_collection: bool, collection: str) -> None:
    """Delete the playlists, then (if scoped) clear the app-wide collection."""
    if app_key == "music":
        from connections import musickit
        for name in targets:
            # One playlist Music.app refuses to script (e.g. a smart/managed playlist
            # → AppleScript -10003 "Access not allowed") must not abort the batch.
            try:
                res = musickit.delete_apple_playlist(name)
            except RuntimeError as e:
                console.print(f"  [yellow]skipped[/yellow] {name}: Apple Music refused — {e}")
                continue
            console.print(f"  [green]deleted[/green] {name}" if res["deleted"]
                          else f"  [yellow]not found in Apple Music[/yellow]: {name}")
        if do_collection:
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
        if do_collection:
            console.print("Clearing Spotify Liked Songs…")
            n = client.clear_saved_tracks()
            console.print(f"  [green]cleared[/green] Liked Songs — {n} track(s) removed")
    finally:
        client.close()


# ── beatport delete / ad-hoc push ────────────────────────────────────────────

def _delete_beatport_playlists(args) -> None:
    """`beatport delete --all` — delete EVERY real Beatport playlist, keep enriched_tracks.

    Targets are resolved live from the Beatport account (what actually exists to
    delete). Pull-first runs `dj sync beatport pull` once (all playlists, one log +
    summary) so their tracks land in enriched_tracks before the playlists are
    removed. Beatport has no library/liked collection, so the only scope is --all.
    """
    from rich.prompt import Confirm

    from connections.beatport import AuthExpiredError, make_bp_client

    if args.scope != "all":
        console.print("[red]Error:[/red] beatport delete requires --all.")
        sys.exit(1)

    def _auth_failed(e: Exception, deleted: int | None = None) -> None:
        console.print(f"[red]Beatport auth failed:[/red] {e}")
        if deleted is not None:
            console.print(f"[yellow]Deleted {deleted} of {len(targets)} before the session expired.[/yellow]")
        console.print("[dim]Sign out and back into beatport.com in your default browser to "
                      "rotate the session cookie, then re-run.[/dim]")
        sys.exit(1)

    beatport, client = make_bp_client()
    try:
        try:
            targets = [(int(pl["id"]), pl.get("name") or str(pl["id"]))
                       for pl in beatport.list_my_playlists()]
        except AuthExpiredError as e:
            _auth_failed(e)
        if not targets:
            console.print("[yellow]No Beatport playlists to delete.[/yellow]")
            return

        console.print(f"[bold]Delete from Beatport[/bold]: {len(targets)} playlist(s)")
        shown = ", ".join(n for _, n in targets[:30]) + (
            f" … (+{len(targets) - 30})" if len(targets) > 30 else "")
        console.print(f"[dim]  playlists: {shown}[/dim]")
        console.print("[dim]Removed from Beatport only; enriched_tracks is kept.[/dim]")

        if args.dry_run:
            console.print("[yellow]DRY RUN[/yellow] — nothing pulled or deleted.")
            return

        if not args.no_sync and (args.yes or Confirm.ask(
                "Pull each playlist into enriched_tracks first so your backup is current?",
                default=True)):
            # One pull of ALL playlists — identical to `dj sync beatport pull` (one log,
            # one summary). Looping per playlist would emit a separate log + summary each.
            from detect.sync_beatport import run_sync_beatport
            run_sync_beatport(dry_run=False, verbose=False, limit=0, playlist=None)

        if not args.yes and not Confirm.ask(
                f"Delete all {len(targets)} playlists from Beatport? This can't be undone.",
                default=False):
            console.print("Aborted — nothing deleted.")
            return

        deleted = 0
        try:
            for pid, name in targets:
                beatport.delete_playlist(pid)
                console.print(f"  [green]deleted[/green] {name}")
                deleted += 1
        except AuthExpiredError as e:
            # Session died mid-batch; every remaining DELETE would 401 too. Report the
            # partial state (the deleted playlists are already gone) and how to recover.
            _auth_failed(e, deleted)
        console.print(f"[green]Done[/green] — deleted {deleted} playlist(s) from Beatport "
                      "(enriched_tracks kept).")
    finally:
        client.close()


def _beatport_playlist_push(args) -> None:
    """`beatport push --name` — selected enriched_tracks → a Beatport playlist.

    Tracks are chosen by `--ids` (beatport_ids) or a `--query` returning a
    beatport_id column, then created as / merged into a named Beatport playlist.
    Wraps the shared `export.to_beatport.push_to_beatport` (same engine as
    `dj export beatport`).
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
