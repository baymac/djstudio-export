"""Push beatport_ids to a Beatport playlist or a Beatport chart.

Charts are a distinct API object from playlists (see connections/beatport.py):
they hang off the DJ profile and are publishable. Insertion order becomes the
chart position, so callers must pass beatport_ids already in set order.
"""
from __future__ import annotations

from typing import Optional, Sequence

from rich.console import Console

_DEFAULT_CONSOLE = Console()


def push_to_beatport(
    beatport_ids: Sequence[int],
    playlist_name: str,
    *,
    dry_run: bool = False,
    console: Optional[Console] = None,
) -> None:
    console = console or _DEFAULT_CONSOLE
    if not beatport_ids:
        console.print("[yellow]No tracks to push.[/yellow]")
        return

    from sync.sync import make_bp_client

    beatport, client = make_bp_client()
    try:
        existing = beatport.list_my_playlists()
        match = next((p for p in existing if p["name"] == playlist_name), None)
        playlist_id = None
        if match:
            playlist_id = match["id"]
            console.print(f"[dim]Reusing playlist '{playlist_name}' (id={playlist_id})[/dim]")
        elif dry_run:
            console.print(f"[dim]Would create playlist '{playlist_name}'[/dim]")
        else:
            created = beatport.create_playlist(playlist_name)
            playlist_id = created.get("id")
            if not playlist_id:
                console.print(f"[red]Failed to create playlist '{playlist_name}'[/red]")
                return
            console.print(f"[green]Created[/green] playlist '{playlist_name}' (id={playlist_id})")

        existing_ids: set[int] = set()
        if playlist_id is not None and not dry_run:
            existing_ids = beatport.list_track_ids(playlist_id)

        new_ids = [int(bp) for bp in beatport_ids if int(bp) not in existing_ids]
        skipped = len(beatport_ids) - len(new_ids)

        console.print(
            f"[bold]export → Beatport playlist[/bold] ← {len(new_ids)} new, "
            f"{skipped} already in playlist  →  [yellow]{playlist_name}[/yellow]"
        )

        if dry_run or not new_ids or playlist_id is None:
            return

        added = 0
        failed = 0
        for bp in new_ids:
            try:
                beatport.add_track(playlist_id, bp)
                added += 1
            except Exception as e:
                failed += 1
                console.print(f"  [yellow]Failed bp:{bp}: {e}[/yellow]")

        console.print(f"[green]Done.[/green]  added={added}  failed={failed}")
    finally:
        client.close()


def push_to_beatport_chart(
    beatport_ids: Sequence[int],
    chart_name: str,
    *,
    description: Optional[str] = None,
    dry_run: bool = False,
    console: Optional[Console] = None,
) -> None:
    """Create (or reuse) a Beatport chart and add tracks in the given order.

    Tracks are added one at a time (no /bulk/ route on charts); Beatport assigns
    an incrementing position per add, so `beatport_ids` order == chart order. The
    chart is created as an UNPUBLISHED draft — publish it from beatport.com.
    """
    console = console or _DEFAULT_CONSOLE
    if not beatport_ids:
        console.print("[yellow]No tracks to push.[/yellow]")
        return

    from sync.sync import make_bp_client

    beatport, client = make_bp_client()
    try:
        existing = beatport.list_my_charts()
        match = next((c for c in existing if c["name"] == chart_name), None)
        chart_id = None
        if match:
            chart_id = match["id"]
            console.print(f"[dim]Reusing chart '{chart_name}' (id={chart_id})[/dim]")
            if description and not dry_run:
                beatport.update_chart(chart_id, description=description)
        elif dry_run:
            console.print(f"[dim]Would create chart '{chart_name}'[/dim]")
        else:
            created = beatport.create_chart(chart_name, description=description)
            chart_id = created.get("id")
            if not chart_id:
                console.print(f"[red]Failed to create chart '{chart_name}'[/red]")
                return
            console.print(f"[green]Created[/green] chart '{chart_name}' (id={chart_id})")

        existing_ids: set[int] = set()
        if chart_id is not None and not dry_run:
            existing_ids = beatport.list_chart_track_ids(chart_id)

        new_ids = [int(bp) for bp in beatport_ids if int(bp) not in existing_ids]
        skipped = len(beatport_ids) - len(new_ids)

        console.print(
            f"[bold]export → Beatport chart[/bold] ← {len(new_ids)} new, "
            f"{skipped} already in chart  →  [yellow]{chart_name}[/yellow]"
        )

        if dry_run or not new_ids or chart_id is None:
            return

        added = 0
        failed = 0
        for bp in new_ids:
            try:
                if beatport.add_chart_track(chart_id, bp):
                    added += 1
            except Exception as e:
                failed += 1
                console.print(f"  [yellow]Failed bp:{bp}: {e}[/yellow]")

        console.print(f"[green]Done.[/green]  added={added}  failed={failed}")
        console.print(
            "[dim]Chart is an unpublished draft — publish at beatport.com "
            "→ DJ profile → Charts.[/dim]"
        )
    finally:
        client.close()
