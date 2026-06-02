"""Argparse CLI for `dj export ...` — the single home for pushing tracks out.

Three forms:
  * `dj export set <id> --to bp_chart|bp_playlist|rekordbox`  — a stored set by id
  * `dj export beatport  --query SQL --name NAME`             — ad-hoc SQL → Beatport playlist
  * `dj export rekordbox --query SQL --name NAME`             — ad-hoc SQL → rekordbox playlist

`set` is decoupled from the set builder (builder writes a set + returns an id;
this pushes it). The `beatport`/`rekordbox` verbs run a user SQL query (must
SELECT beatport_id) and push the result — the old `dj playlist` command folded
in here. Core logic: export/export_set.py + export/to_*.py.
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console

console = Console()


def add_export_subparser(parent) -> argparse.ArgumentParser:
    p = parent.add_parser(
        "export",
        help="Export a stored set, or a SQL-curated subset, to Beatport / rekordbox.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  dj export set 42 --to bp_chart\n"
            "  dj export set 42 --to bp_playlist --name \"Peak Time\"\n"
            "  dj export set 42 --to rekordbox --dry-run\n"
            "  dj export beatport  --query \"SELECT beatport_id FROM enriched_tracks "
            "WHERE genre='Tech House' AND bpm BETWEEN 124 AND 128\" --name \"Peak Tech\"\n"
            "  dj export rekordbox --query \"SELECT e.beatport_id FROM enriched_tracks e "
            "JOIN enriched_tracks_analysis a USING(beatport_id) WHERE a.mik_nrg>=7\" "
            "--name \"High Energy\"\n"
        ),
    )
    sub = p.add_subparsers(dest="export_command")

    s = sub.add_parser("set", help="Export a stored set by its id.")
    s.add_argument("id", type=int, help="set id (from the set builder / build_set.py)")
    s.add_argument(
        "--to", required=True,
        choices=["bp_chart", "bp_playlist", "rekordbox"],
        help="export destination",
    )
    s.add_argument(
        "--name", "-n",
        help="destination chart/playlist name (default: the set's stored name)",
    )
    s.add_argument(
        "--description",
        help="chart description (bp_chart only; default built from the set's mood/duration)",
    )
    s.add_argument("--dry-run", action="store_true",
                   help="show what would happen without writing.")

    # Ad-hoc SQL-curated push (the former `dj playlist <dest>`).
    for dest_name, dest_help in [
        ("beatport", "Run a SQL query and push the result to a Beatport playlist."),
        ("rekordbox", "Run a SQL query and push the result to a rekordbox playlist."),
    ]:
        d = sub.add_parser(dest_name, help=dest_help)
        d.add_argument(
            "--query", "-q", required=True,
            help="SQL against enriched_tracks (and/or enriched_tracks_analysis). "
                 "Must SELECT beatport_id.",
        )
        d.add_argument("--name", "-n", required=True,
                       help="Destination playlist name.")
        d.add_argument("--dry-run", action="store_true",
                       help="show what would happen without writing.")

    return p


def dispatch(args, p: argparse.ArgumentParser) -> None:
    cmd = getattr(args, "export_command", None)
    if cmd not in ("set", "beatport", "rekordbox"):
        p.print_help()
        return

    from paths import command_logger

    if cmd == "set":
        with command_logger(f"export-{args.to}", console) as log_path:
            console.print(f"[dim]Log: {log_path}[/dim]")
            from export.export_set import export_set
            ok = export_set(
                args.id, args.to,
                name=args.name, description=args.description,
                dry_run=args.dry_run, console=console,
            )
            if not ok:
                sys.exit(1)
        return

    # beatport / rekordbox: ad-hoc SQL → destination
    with command_logger(f"export-{cmd}", console) as log_path:
        console.print(f"[dim]Log: {log_path}[/dim]")
        _dispatch_query(args, cmd)


def _dispatch_query(args, cmd: str) -> None:
    from playlist.query import run_user_query, fetch_full_rows

    try:
        beatport_ids = run_user_query(args.query)
    except ValueError as e:
        console.print(f"[red]Query error:[/red] {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]SQL error:[/red] {e}")
        sys.exit(1)

    if not beatport_ids:
        console.print("[yellow]Query returned no rows.[/yellow]")
        return

    console.print(f"[dim]Query → {len(beatport_ids)} unique beatport_ids[/dim]")
    rows = fetch_full_rows(beatport_ids)
    if len(rows) < len(beatport_ids):
        console.print(
            f"[yellow]{len(beatport_ids) - len(rows)} of {len(beatport_ids)} "
            f"beatport_ids have no row in enriched_tracks[/yellow]"
        )

    if cmd == "beatport":
        from export.to_beatport import push_to_beatport
        push_to_beatport(beatport_ids, args.name, dry_run=args.dry_run, console=console)
    else:  # rekordbox
        from export.to_rekordbox import push_to_rekordbox
        push_to_rekordbox(rows, args.name, dry_run=args.dry_run, console=console)
