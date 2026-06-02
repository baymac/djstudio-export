"""Argparse CLI for `dj enrich` — the single home for building the enriched library.

`dj enrich` runs Beatport metadata enrichment over BOTH track sources by default:

  * detected tracks  (`detected_tracks` → `enriched_tracks`, via `enrich.engine`)
  * synced tracks     (`sync_tracks`     → `enriched_tracks`, via `sync.enrich_adapter`)

Scope it to one source with `--detect` or `--sync`. A second verb, `analyse`, runs
DJ Studio's headless SDK analysis over the enriched tracks and writes the result
to `enriched_tracks_analysis` (no DJ Studio filesystem writes).

  dj enrich                       enrich detected + synced tracks (default: both)
  dj enrich --detect              only detected tracks
  dj enrich --sync                only synced tracks
  dj enrich [--dry-run] [--limit N] [--verbose] [--threshold F] [--retry-misses]
  dj enrich analyse [--ids ID,...] [--limit N] [--force] [--retry-failed] [--verbose]
"""
from __future__ import annotations

import argparse
import sys

from rich.console import Console

from connections import matching

console = Console()


def add_enrich_subparser(parent) -> argparse.ArgumentParser:
    enrich_p = parent.add_parser(
        "enrich",
        help="Enrich detected + synced tracks with Beatport metadata; `analyse` runs DJ Studio SDK.",
    )
    enrich_p.add_argument("--detect", dest="only_detect", action="store_true",
                          help="Only enrich detected tracks (detected_tracks).")
    enrich_p.add_argument("--sync", dest="only_sync", action="store_true",
                          help="Only enrich synced tracks (sync_tracks).")
    enrich_p.add_argument("--dry-run", action="store_true",
                          help="Show what would be enriched without writing to DB.")
    enrich_p.add_argument("--limit", type=int, default=0, metavar="N",
                          help="Stop after N tracks per source (0 = no limit).")
    enrich_p.add_argument("--verbose", "-v", action="store_true",
                          help="Print Beatport search details.")
    enrich_p.add_argument("--threshold", type=float, default=matching.MATCH_THRESHOLD, metavar="F",
                          help=f"Fuzzy match threshold 0-1 (default: {matching.MATCH_THRESHOLD}).")
    enrich_p.add_argument("--retry-misses", "-r", action="store_true",
                          help="Retry tracks that previously had no results or a fuzzy miss.")

    en_sub = enrich_p.add_subparsers(dest="enrich_command")
    en_sub.required = False

    # ── analyse (DJ Studio SDK → enriched_tracks_analysis) ──────────────────────
    an_p = en_sub.add_parser(
        "analyse",
        help="Run DJ Studio's SDK analysis and write directly to enriched_tracks_analysis "
             "(no DJ Studio filesystem writes).",
    )
    an_p.add_argument("--ids", default=None, metavar="ID[,ID...]",
                      help="Comma-separated beatport IDs to analyze. When set, --limit is ignored.")
    an_p.add_argument("--limit", type=int, default=0, metavar="N",
                      help="Stop after N tracks (0 = no limit).")
    an_p.add_argument("--verbose", "-v", action="store_true")
    an_p.add_argument("--force", action="store_true",
                      help="Re-process tracks even if a row already exists in enriched_tracks_analysis.")
    an_p.add_argument("--retry-failed", action="store_true",
                      help="Ignore the hard-failure sidecar and re-attempt tracks that previously "
                           "hit MAX_FAILURE_ATTEMPTS.")

    return enrich_p


def dispatch(args, enrich_p: argparse.ArgumentParser) -> None:
    from detect.db import migrate
    from sync import db as sync_db

    # Both sources write to the same dj.db; ensure both schemas exist before either runs.
    migrate()
    sync_db.init_db()

    if getattr(args, "enrich_command", None) == "analyse":
        _run_analyse(args)
        return

    only_detect = getattr(args, "only_detect", False)
    only_sync = getattr(args, "only_sync", False)
    if only_detect and only_sync:
        console.print("[red]Error:[/red] --detect and --sync are mutually exclusive "
                      "(omit both to enrich all sources).")
        sys.exit(1)

    run_detect = not only_sync
    run_sync = not only_detect

    if run_detect:
        console.print("[bold cyan]Enrich → detected tracks[/bold cyan]")
        from enrich.engine import run_enrich
        run_enrich(
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
            threshold=args.threshold,
            retry_misses=args.retry_misses,
        )

    if run_sync:
        if run_detect:
            console.print()
        console.print("[bold cyan]Enrich → synced tracks[/bold cyan]")
        from sync.enrich_adapter import run_sync_enrich
        run_sync_enrich(
            dry_run=args.dry_run,
            limit=args.limit,
            verbose=args.verbose,
            threshold=args.threshold,
            retry_misses=args.retry_misses,
        )


def _run_analyse(args) -> None:
    from enrich.analyse import run_studio_analyse

    ids = None
    if args.ids:
        try:
            ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        except ValueError:
            console.print(f"[red]--ids must be comma-separated integers, got: {args.ids}[/red]")
            return
    run_studio_analyse(
        ids=ids,
        limit=args.limit,
        verbose=args.verbose,
        force=args.force,
        retry_failed=args.retry_failed,
    )
