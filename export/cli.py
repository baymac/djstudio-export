"""Argparse CLI for `dj export set <id> --to bp_chart|bp_playlist|rekordbox`.

Export is intentionally decoupled from the set builder: the builder writes a set
to the DB and returns an id; this tool takes that id and pushes the set's tracks
(in set order) to a destination. See export/export_set.py for the core.
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console

console = Console()


def add_export_subparser(parent) -> argparse.ArgumentParser:
    p = parent.add_parser(
        "export",
        help="Export a stored set to a Beatport chart/playlist or rekordbox.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  dj export set 42 --to bp_chart\n"
            "  dj export set 42 --to bp_playlist --name \"Peak Time\"\n"
            "  dj export set 42 --to rekordbox --dry-run\n"
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

    return p


def dispatch(args, p: argparse.ArgumentParser) -> None:
    cmd = getattr(args, "export_command", None)
    if cmd != "set":
        p.print_help()
        return

    from paths import command_logger

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
