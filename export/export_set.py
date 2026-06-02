"""Export a stored set (dj_sets) to a Beatport chart, Beatport playlist, or rekordbox.

This is the coupling point the builder (`helpers/build_set.py`) deliberately does
NOT have: `build_set` only writes a set to the DB and hands back an id; this module
takes that id and pushes the set's tracks to a destination, in set order.

    export_set(set_id, "bp_chart")       # Beatport chart (publishable draft)
    export_set(set_id, "bp_playlist")    # Beatport playlist
    export_set(set_id, "rekordbox")      # rekordbox playlist (rekordbox must be quit)
"""
from __future__ import annotations

import json
from typing import Optional

from rich.console import Console

from detect import db as detect_db

_DEFAULT_CONSOLE = Console()

DESTINATIONS = ("bp_chart", "bp_playlist", "rekordbox")


def _params(header) -> dict:
    raw = header["params_json"] if "params_json" in header.keys() else None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _default_chart_description(header, params: dict) -> Optional[str]:
    """Build a short chart description from the set's stored provenance."""
    bits: list[str] = []
    mood = (params.get("mood") or "").strip()
    if mood:
        bits.append(mood)
    duration = params.get("duration_min")
    if duration:
        bits.append(f"{duration}-min set")
    archetype = header["type"]
    if archetype:
        bits.append(f"[{archetype}]")
    return " · ".join(bits) or None


def export_set(
    set_id: int,
    to: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    dry_run: bool = False,
    console: Optional[Console] = None,
) -> bool:
    """Export the set `set_id` to destination `to`. Returns True on success.

    `name` overrides the destination chart/playlist name (defaults to the set's
    stored name). `description` applies only to `bp_chart` (defaults to a short
    line built from the set's mood/duration/archetype).
    """
    console = console or _DEFAULT_CONSOLE
    if to not in DESTINATIONS:
        console.print(f"[red]Unknown destination {to!r} (expected one of {', '.join(DESTINATIONS)}).[/red]")
        return False

    detect_db.migrate()
    header = detect_db.get_set(set_id)
    if header is None:
        console.print(f"[red]No set with id {set_id}.[/red] Build one first with the set builder.")
        return False

    tracks = detect_db.tracks_in_set_id(set_id)
    beatport_ids = [int(t["beatport_id"]) for t in tracks]
    if not beatport_ids:
        console.print(f"[yellow]Set {set_id} ('{header['name']}') has no tracks.[/yellow]")
        return False

    dest_name = name or header["name"]
    params = _params(header)
    console.print(
        f"[dim]Set {set_id} '{header['name']}' [{header['type']}] → {len(beatport_ids)} tracks[/dim]"
    )

    if to == "bp_playlist":
        from export.to_beatport import push_to_beatport
        push_to_beatport(beatport_ids, dest_name, dry_run=dry_run, console=console)
    elif to == "bp_chart":
        from export.to_beatport import push_to_beatport_chart
        push_to_beatport_chart(
            beatport_ids, dest_name,
            description=description or _default_chart_description(header, params),
            dry_run=dry_run, console=console,
        )
    elif to == "rekordbox":
        from export.to_rekordbox import push_to_rekordbox
        from playlist.query import fetch_full_rows
        rows = fetch_full_rows(beatport_ids)
        missing = len(beatport_ids) - len(rows)
        if missing:
            console.print(
                f"[yellow]{missing} of {len(beatport_ids)} tracks have no enriched_tracks "
                f"row and will be skipped.[/yellow]"
            )
        push_to_rekordbox(rows, dest_name, dry_run=dry_run, console=console)
        if not dry_run:
            console.print(
                f"\n[dim]Next:[/dim] open rekordbox → find the [yellow]{dest_name}[/yellow] "
                "playlist → right-click → [cyan]Analyze Tracks[/cyan] to generate beatgrid + cues."
            )

    return True
