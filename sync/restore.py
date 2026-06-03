"""`dj sync music playlist push --all/--playlists/--library/--favorite-only` — restore from dj.db.

The inverse of capture: rebuild Apple Music's contents from the faithful `sync_tracks`
backup. Apple Music only — Spotify push adds tracks by id with no re-add problem.

Scopes (run in this order for `--all`):
  library    re-add captured `__library__` tracks to the library (catalog re-add)
  playlists  recreate every captured user playlist (matches tracks now in the library)
  favorites  re-mark captured `__favorites__` tracks as loved

`--readd-missing` limits work to tracks NOT already in the library (idempotent and
resumable — Ctrl-C and re-run to continue). macOS has no supported API to add a
catalog track to the library, so the re-add is the best-effort `itmss://` trick:
region-locked / removed tracks are skipped, which the user has accepted.
"""
from __future__ import annotations

import time

from rich.console import Console

from connections import musickit
from sync import db as sync_db

console = Console()

APP = "apple_music"
LIBRARY_PID = "__library__"
FAVORITES_PID = "__favorites__"
_READD_PAUSE = 0.3  # seconds between itmss opens so Music.app keeps up


def _row(r) -> dict:
    return {
        "title": r["title"],
        "artist": r["artist"],
        "album": r["album"],
        "native_track_id": r["native_track_id"],
        "native_persistent_id": r["native_persistent_id"],
    }


def restore_music(*, scopes: set[str], readd_missing: bool, dry_run: bool, verbose: bool) -> None:
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — nothing will be added or changed")

    # library first (repopulate) → playlists (match the now-present tracks) → favorites.
    if "library" in scopes:
        _restore_library(readd_missing, dry_run, verbose)
    if "playlists" in scopes:
        _restore_playlists(readd_missing, dry_run, verbose)
    if "favorites" in scopes:
        _restore_favorites(readd_missing, dry_run, verbose)


def _drop_present(rows: list[dict]) -> tuple[list[dict], int]:
    """Drop rows whose track is already in the library (for --readd-missing). Returns (missing, n_present)."""
    have = musickit.read_library_track_keys()
    missing = [r for r in rows if musickit.library_track_key(r["title"], r["artist"]) not in have]
    return missing, len(rows) - len(missing)


def _readd(rows: list[dict], dry_run: bool) -> int:
    """Best-effort itmss catalog re-add, paced so Music.app keeps up. Returns attempts."""
    attempted = 0
    for r in rows:
        cid = r["native_track_id"]
        if not cid:
            continue
        attempted += 1
        if dry_run:
            continue
        musickit.readd_track_by_catalog_id(cid)
        time.sleep(_READD_PAUSE)
    return attempted


def _restore_library(readd_missing: bool, dry_run: bool, verbose: bool) -> None:
    rows = [_row(r) for r in sync_db.tracks_in_native_playlist(APP, LIBRARY_PID)]
    if not rows:
        console.print("[yellow]No captured library tracks — run `dj sync music --library` first.[/yellow]")
        return
    present = 0
    if readd_missing and not dry_run:
        rows, present = _drop_present(rows)
    console.print(f"[bold]Restore library[/bold]: {len(rows)} track(s) to re-add"
                  + (f"  [dim]({present} already present, skipped)[/dim]" if present else ""))
    n = _readd(rows, dry_run)
    verb = "would re-add" if dry_run else "re-added (best-effort)"
    note = "" if dry_run else "  [dim]— itmss is experimental; region-locked/removed won't land[/dim]"
    console.print(f"  [green]{verb}[/green] {n} track(s){note}")


def _restore_playlists(readd_missing: bool, dry_run: bool, verbose: bool) -> None:
    playlists = [r for r in sync_db.list_playlists(APP)
                 if r["native_playlist_id"] not in (LIBRARY_PID, FAVORITES_PID)]
    if not playlists:
        console.print("[yellow]No captured playlists to restore.[/yellow]")
        return
    console.print(f"[bold]Restore {len(playlists)} playlist(s)[/bold] "
                  "[dim](creates new playlists; matches tracks in the library)[/dim]")
    for p in playlists:
        npid, name = p["native_playlist_id"], (p["playlist_name"] or p["native_playlist_id"])
        rows = [_row(r) for r in sync_db.tracks_in_native_playlist(APP, npid)]
        if readd_missing and not dry_run:
            missing, _ = _drop_present(rows)
            _readd(missing, dry_run)
        if dry_run:
            console.print(f"  [dim]would recreate[/dim] {name}: {len(rows)} tracks")
            continue
        res = musickit.create_apple_playlist(name, rows)
        miss = res["requested"] - res["added"]
        tail = f"  [yellow]({miss} not in library)[/yellow]" if miss else ""
        console.print(f"  [green]recreated[/green] {name}: {res['added']}/{res['requested']} tracks{tail}")


def _restore_favorites(readd_missing: bool, dry_run: bool, verbose: bool) -> None:
    rows = [_row(r) for r in sync_db.tracks_in_native_playlist(APP, FAVORITES_PID)]
    if not rows:
        console.print("[yellow]No captured favorites — run `dj sync music --favorite-only` first.[/yellow]")
        return
    if readd_missing and not dry_run:
        missing, _ = _drop_present(rows)
        _readd(missing, dry_run)
    console.print(f"[bold]Restore favorites[/bold]: {len(rows)} track(s)")
    if dry_run:
        console.print(f"  [dim]would mark loved[/dim]: {len(rows)}")
        return
    n = musickit.mark_loved(rows)
    console.print(f"  [green]marked loved[/green]: {n}/{len(rows)}")


# ── Spotify (clean — the Web API adds tracks by id; no catalog re-add needed) ──────

SPOTIFY = "spotify"


def restore_spotify(*, scopes: set[str], dry_run: bool, verbose: bool) -> None:
    """Rebuild Spotify from the backup. `--library` = re-save Liked Songs; `--playlists`
    = recreate every captured playlist. No favorites/re-add: the API adds by id."""
    import sys

    from connections import spotify as sp
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — nothing will be added or changed")

    if "playlists" in scopes:
        rows_by_pl = [(p["native_playlist_id"], p["playlist_name"] or p["native_playlist_id"])
                      for p in sync_db.list_playlists(SPOTIFY)
                      if p["native_playlist_id"] != LIBRARY_PID]
        console.print(f"[bold]Restore {len(rows_by_pl)} Spotify playlist(s)[/bold]")
    do_library = "library" in scopes

    if dry_run:
        if "playlists" in scopes:
            for npid, name in rows_by_pl:
                n = len(sync_db.tracks_in_native_playlist(SPOTIFY, npid))
                console.print(f"  [dim]would recreate[/dim] {name}: {n} tracks")
        if do_library:
            n = len(sync_db.tracks_in_native_playlist(SPOTIFY, LIBRARY_PID))
            console.print(f"[bold]Restore Liked Songs[/bold]: [dim]would re-save[/dim] {n} tracks")
        return

    try:
        client = sp.make_client()
    except sp.SpotifyAuthError as e:
        console.print(f"[red]Spotify auth:[/red] {e}")
        sys.exit(1)
    try:
        if "playlists" in scopes:
            user_id = client.current_user_id()
            for npid, name in rows_by_pl:
                ids = [r["native_track_id"] for r in sync_db.tracks_in_native_playlist(SPOTIFY, npid)
                       if r["native_track_id"]]
                pid = client.create_playlist(user_id, name)
                added = client.add_tracks(pid, ids)
                console.print(f"  [green]recreated[/green] {name}: {added} tracks")
        if do_library:
            ids = [r["native_track_id"] for r in sync_db.tracks_in_native_playlist(SPOTIFY, LIBRARY_PID)
                   if r["native_track_id"]]
            saved = client.save_tracks(ids)
            console.print(f"[green]Re-saved Liked Songs[/green]: {saved} tracks")
    finally:
        client.close()


# ── Beatport (recreate playlists on the account from beatport_playlists) ───────────


def restore_beatport(*, dry_run: bool, verbose: bool) -> None:
    """Recreate every captured Beatport playlist on the account (create + add by id)."""
    import sys

    from connections.beatport import make_bp_client
    from detect import db as detect_db

    playlists = detect_db.list_beatport_playlists()
    if not playlists:
        console.print("[yellow]No captured Beatport playlists — run `dj sync beatport` first.[/yellow]")
        return
    console.print(f"[bold]Restore {len(playlists)} Beatport playlist(s)[/bold]")

    if dry_run:
        for p in playlists:
            ids = detect_db.beatport_track_ids_in_playlist(p["beatport_id"])
            console.print(f"  [dim]would recreate[/dim] {p['name']}: {len(ids)} tracks")
        return

    beatport, client = make_bp_client()
    try:
        for p in playlists:
            ids = detect_db.beatport_track_ids_in_playlist(p["beatport_id"])
            new = beatport.create_playlist(p["name"])
            new_id = new.get("id")
            added = 0
            for tid in ids:
                try:
                    beatport.add_track(new_id, tid)
                    added += 1
                except Exception:  # noqa: BLE001 — skip a track that won't add, keep going
                    pass
            console.print(f"  [green]recreated[/green] {p['name']}: {added}/{len(ids)} tracks")
    finally:
        client.close()
