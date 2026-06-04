"""Enrich tracks with Beatport metadata (bpm, key, genre, release_date, beatport_id, beatport_link).

The matching/search loop is a SHARED ENGINE (`run_enrich_engine`) parameterised by a
`SourceAdapter`. `dj enrich metadata --detect` drives it with `DetectAdapter` (candidates from
`detected_tracks`); `dj enrich metadata --sync` drives the same engine with a sync adapter
(candidates from `sync_tracks`) — see `sync/enrich_adapter.py`. Both write to the one
deduped `enriched_tracks` table. "Keep the code the same" is literal: one loop, two
thin persistence adapters.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol

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

from caffeinate import caffeinate
from connections import beatport as bp_api
from connections.matching import MATCH_THRESHOLD, best_match, search_query, split_mashup_variants, strip_remix
from detect import db as detect_db
from detect.db import get_enriched_artist_titles, mark_enrich_miss

console = Console()

from paths import LOGS_DIR as _LOGS_ROOT
_LOG_DIR = _LOGS_ROOT / "enrich"

# Matches any parenthetical/bracketed tag that contains a version/mix keyword
# e.g. "(Ezel Extended)", "(Daniele Busciala Extended)", "(Radio Edit)", "(Instrumental)"
_VERSION_TAG_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(?:extended|original|radio|club|instrumental|acapella|vip|dub|"
    r"mix|edit|version|remix|rework|bootleg|mashup|flip)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def _base_key(artist: str, title: str) -> tuple[str, str]:
    """Normalised (artist, title) pair for version-variant deduplication."""
    stripped = _VERSION_TAG_RE.sub("", title).strip().lower()
    return (artist.lower().strip(), stripped)


def _get_token() -> str:
    token = bp_api.resolve_access_token()
    if token:
        return token
    console.print(
        "[red]Beatport token expired and session refresh failed.[/red]\n"
        "Tried env session cookie and the browser cookie store. "
        "Log into beatport.com in your default browser, then re-run."
    )
    sys.exit(1)


def _try_refresh() -> Optional[str]:
    return bp_api.resolve_access_token(force_refresh=True)


def _bp_meta(match: dict) -> dict:
    """Extract enrichment fields from a Beatport search result."""
    slug = match.get("slug", "")
    track_id = match.get("id")
    link = f"https://www.beatport.com/track/{slug}/{track_id}" if slug and track_id else ""
    key_obj = match.get("key") or {}
    release_obj = match.get("release") or {}
    release_date = (
        match.get("publish_date")
        or match.get("new_release_date")
        or (release_obj.get("date") if isinstance(release_obj, dict) else None)
        or match.get("release_date")
    )
    return {
        "beatport_id": track_id,
        "beatport_link": link,
        "bpm": match.get("bpm"),
        "key": key_obj.get("camelot_name") or key_obj.get("name"),
        "genre": (match.get("genre") or {}).get("name"),
        "release_date": release_date,
    }


def _fetch_extras(beatport: "bp_api.Beatport", beatport_id: int) -> dict:
    """Fetch full Beatport catalog detail (label/ISRC/sub_genre/mix_name/length).

    Non-critical: any failure returns {} so the basic enrich still succeeds.
    """
    try:
        full_track = beatport.get_track(beatport_id)
        if not full_track:
            return {}
        label_obj = (full_track.get("release") or {}).get("label") or {}
        sub_genre_obj = full_track.get("sub_genre") or {}
        return {
            "mix_name": full_track.get("mix_name"),
            "label": label_obj.get("name") if isinstance(label_obj, dict) else None,
            "catalog_number": full_track.get("catalog_number"),
            "isrc": full_track.get("isrc"),
            "sub_genre": sub_genre_obj.get("name") if isinstance(sub_genre_obj, dict) else None,
            "length_ms": full_track.get("length_ms"),
        }
    except Exception:
        return {}


# ── Source adapters ───────────────────────────────────────────────────────────
# The engine persists through one of these. Each maps the generic enrich
# vocabulary onto a concrete source table (detected_tracks or sync_tracks).


class SourceAdapter(Protocol):
    name: str

    def load_candidates(self, retry_misses: bool) -> list: ...
    def secret_count(self) -> int: ...
    def mark_secret(self, row_id: int) -> None: ...
    def mark_miss(self, row_id: int, outcome: str) -> None: ...
    def seen_pairs(self) -> list: ...
    def link_existing(self, row_id: int, beatport_id: int) -> bool: ...
    def save_enriched(self, row_id: int, meta: dict, extras: dict) -> None: ...
    def insert_extra(self, artist: str, title: str, source: str) -> int: ...
    def start_run(self) -> int: ...
    def finish_run(self, run_id: int, seen: int, found: int, not_found: int,
                   fuzzy_miss: int, duplicate: int) -> None: ...


class DetectAdapter:
    """Adapter over `detected_tracks` — backs `dj enrich --detect`."""

    name = "Enrich"

    def load_candidates(self, retry_misses: bool) -> list:
        return detect_db.get_retry_tracks() if retry_misses else detect_db.get_unenriched_tracks()

    def secret_count(self) -> int:
        return detect_db.count_secret_tracks()

    def mark_secret(self, row_id: int) -> None:
        detect_db.mark_enrich_miss(row_id, "secret")

    def mark_miss(self, row_id: int, outcome: str) -> None:
        mark_enrich_miss(row_id, outcome)

    def seen_pairs(self) -> list:
        return get_enriched_artist_titles()

    def link_existing(self, row_id: int, beatport_id: int) -> bool:
        return detect_db.link_detected_to_enriched(row_id, beatport_id)

    def save_enriched(self, row_id: int, meta: dict, extras: dict) -> None:
        detect_db.upsert_enriched(row_id, meta, extras=extras)

    def insert_extra(self, artist: str, title: str, source: str) -> int:
        return detect_db.insert_track({"artist": artist, "title": title}, source=source)

    def start_run(self) -> int:
        return detect_db.start_enrich_run()

    def finish_run(self, run_id, seen, found, not_found, fuzzy_miss, duplicate) -> None:
        detect_db.finish_enrich_run(
            run_id, seen=seen, found=found, not_found=not_found,
            fuzzy_miss=fuzzy_miss, duplicate=duplicate,
        )


def run_enrich(
    dry_run: bool,
    limit: int,
    verbose: bool,
    threshold: float,
    retry_misses: bool,
) -> None:
    """`dj enrich --detect` entrypoint — drives the shared engine over detected_tracks."""
    run_enrich_engine(
        DetectAdapter(),
        dry_run=dry_run, limit=limit, verbose=verbose,
        threshold=threshold, retry_misses=retry_misses,
    )


def run_enrich_engine(
    adapter: SourceAdapter,
    *,
    dry_run: bool,
    limit: int,
    verbose: bool,
    threshold: float,
    retry_misses: bool,
) -> None:
    if dry_run:
        console.print("[yellow]DRY RUN[/yellow] — no changes will be made")

    if retry_misses:
        console.print("Loading previously missed tracks for retry…")
    else:
        console.print("Loading un-enriched tracks…")
    tracks = adapter.load_candidates(retry_misses)
    if limit:
        tracks = tracks[:limit]

    if not tracks:
        secret_n = adapter.secret_count()
        msg = "Nothing to enrich — all tracks already have Beatport data."
        if secret_n:
            msg += f" ({secret_n} secret/ID-placeholder tracks skipped)"
        console.print(msg)
        return

    secret_n = adapter.secret_count()
    secret_note = f"  [dim]({secret_n} secret/ID-placeholder tracks skipped)[/dim]" if secret_n else ""
    console.print(f"[bold]{len(tracks)}[/bold] tracks to enrich{secret_note}")

    beatport, http_client = bp_api.make_bp_client(verbose=verbose)

    run_id = adapter.start_run()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = _LOG_DIR / f"{date_str}_{run_id}.log"
    log_file = log_path.open("w", encoding="utf-8")
    console.print(f"[dim]Log: {log_path}[/dim]")

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    def _log(plain: str, rich_msg: str = "") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        log_file.write(f"{ts}  {plain}\n")
        log_file.flush()
        if verbose:
            progress.log(rich_msg or plain)

    counts = {"seen": 0, "found": 0, "not_found": 0, "fuzzy_miss": 0, "failed": 0, "duplicate": 0, "skipped_id": 0, "mashup_extra": 0}

    # Seed seen base-titles from already-enriched tracks so that version variants
    # enriched in a previous run are also caught.
    # Maps base_key → beatport_id so duplicates can copy the enriched row.
    seen_base_titles: dict[tuple[str, str], int | None] = {
        _base_key(r["artist"], r["title"]): r["beatport_id"]
        for r in adapter.seen_pairs()
        if r["artist"] and r["title"]
    }

    with caffeinate(), progress:
        task = progress.add_task("Enriching…", total=len(tracks))

        for track in tracks:
            counts["seen"] += 1
            progress.update(task, advance=1)

            track_id = track["id"]
            artist = track["artist"] or ""
            title = track["title"] or ""

            progress.update(task, description=f"{artist} — {title}")

            if detect_db.is_id_placeholder(artist) or detect_db.is_id_placeholder(title):
                _log(f"skipped_id  {artist} — {title}")
                if not dry_run:
                    adapter.mark_secret(track_id)
                counts["skipped_id"] += 1
                continue

            bk = _base_key(artist, title)
            if bk in seen_base_titles:
                existing_bp_id = seen_base_titles[bk]
                if not dry_run and existing_bp_id is not None:
                    linked = adapter.link_existing(track_id, existing_bp_id)
                    if linked:
                        counts["duplicate"] += 1
                        _log(
                            f"duplicate  {artist} — {title}  (linked to bp:{existing_bp_id})",
                            f"[dim]duplicate (linked):[/dim] {artist} — {title}",
                        )
                        continue
                _log(
                    f"duplicate  {artist} — {title}  (base title already enriched, no bp_id to link)",
                    f"[dim]duplicate:[/dim] {artist} — {title}",
                )
                if not dry_run:
                    adapter.mark_miss(track_id, "duplicate")
                counts["duplicate"] += 1
                continue
            # Reserve this base title for the current run before the API call
            # so parallel-ish processing within the same batch also deduplicates.
            seen_base_titles[bk] = None  # placeholder until beatport_id is known

            artist_query = re.sub(r"\s*[\(\[].*?[\)\]]", "", artist).strip()
            query = f"{artist_query} {search_query(title)}"
            try:
                results = beatport.search_tracks(query, per_page=10, debug=verbose)
            except bp_api.AuthExpiredError:
                progress.stop()
                console.print(
                    "\n[red]Auth failed:[/red] Beatport session refresh failed after retrying.\n"
                    "Log into beatport.com in your default browser, then re-run."
                )
                http_client.close()
                sys.exit(1)

            if results is None:
                counts["failed"] += 1
                _log(f"search_error  {artist} — {title}",
                     f"[red]search error:[/red] {artist} — {title}")
                continue

            if not results:
                counts["not_found"] += 1
                _log(f"no_results  {artist} — {title}",
                     f"[yellow]no results:[/yellow] {artist} — {title}")
                if not dry_run:
                    adapter.mark_miss(track_id, "not_found")
                continue

            match, score = best_match(title, artist, results, threshold)
            if not match:
                # Retry with base title when a remix/edit/mix tag caused the mismatch.
                # Within that broader search, first try the original title (with remix) in
                # case the remix version appears in results for the base-title query — then
                # fall back to matching the stripped title if it doesn't.
                base_title = strip_remix(title)
                if base_title:
                    base_query = f"{artist_query} {search_query(base_title)}"
                    try:
                        base_results = beatport.search_tracks(base_query, per_page=10, debug=verbose)
                    except bp_api.AuthExpiredError:
                        raise
                    except Exception:
                        base_results = None
                    if base_results:
                        match, score = best_match(title, artist, base_results, threshold)
                        if match:
                            if verbose:
                                progress.log(
                                    f"[green]remix fallback (remix match):[/green] {artist} — {title}  "
                                    f"→  found remix in base search  (score={score:.2f})"
                                )
                        else:
                            match, score = best_match(base_title, artist, base_results, threshold)
                            if match and verbose:
                                progress.log(
                                    f"[green]remix fallback (base match):[/green] {artist} — {title}  "
                                    f"→  matched as base title '{base_title}'  (score={score:.2f})"
                                )

            # SoundCloud uploaders sometimes use "Title - Artist (Mix)" instead of
            # the standard "Artist - Title (Mix)" — re-score the same Beatport
            # results with our artist/title swapped before giving up.
            if not match:
                m, s = best_match(artist, title, results, threshold)
                if m:
                    match, score = m, s
                    if verbose:
                        progress.log(
                            f"[green]swap fallback:[/green] {artist} — {title}  "
                            f"→  re-scored with artist/title swapped  (score={score:.2f})"
                        )

            # Title contains an internal dash (e.g. "Carson Paskill — Jackie Hollander
            # - You Go I Go (Remix)") → split and try the inner pair as artist/title.
            if not match:
                inner = strip_remix(title) or title
                m_inner = re.split(r"\s+-\s+|-\s+", inner, maxsplit=1)
                if len(m_inner) == 2 and m_inner[0].strip() and m_inner[1].strip():
                    inner_artist, inner_title = m_inner[0].strip(), m_inner[1].strip()
                    m, s = best_match(inner_title, inner_artist, results, threshold)
                    if m:
                        match, score = m, s
                        if verbose:
                            progress.log(
                                f"[green]dash-split fallback:[/green] {artist} — {title}  "
                                f"→  parsed as '{inner_artist}' — '{inner_title}'  (score={score:.2f})"
                            )

            # vs. mashup: "A vs. B — T1 vs. T2" → search each component separately.
            # First hit enriches the original row; subsequent hits are stored in
            # split_extras and inserted as new source rows below.
            split_extras: list[tuple[str, str, dict, float]] = []
            if not match:
                for v_title, v_artist in split_mashup_variants(title, artist):
                    v_artist_q = re.sub(r"\s*[\(\[].*?[\)\]]", "", v_artist).strip()
                    try:
                        v_results = beatport.search_tracks(
                            f"{v_artist_q} {search_query(v_title)}", per_page=10, debug=verbose
                        )
                    except bp_api.AuthExpiredError:
                        raise
                    except Exception:
                        v_results = None
                    if not v_results:
                        continue
                    m, s = best_match(v_title, v_artist, v_results, threshold)
                    if not m:
                        continue
                    if not match:
                        match, score = m, s
                        if verbose:
                            progress.log(
                                f"[green]mashup split:[/green] {artist} — {title}  "
                                f"→  matched as '{v_artist} — {v_title}'  (score={s:.2f})"
                            )
                    else:
                        split_extras.append((v_title, v_artist, m, s))

            if not match:
                counts["fuzzy_miss"] += 1
                best_r = results[0]
                bp_artists = ", ".join(a.get("name", "") for a in best_r.get("artists", []))
                _log(
                    f"fuzzy_miss  {artist} — {title}  score={score:.2f}  best: {bp_artists} — {best_r.get('name', '')}",
                    f"[yellow]fuzzy miss:[/yellow] {artist} — {title}  score={score:.2f}",
                )
                if not dry_run:
                    adapter.mark_miss(track_id, "fuzzy_miss")
                continue

            meta = _bp_meta(match)

            if dry_run:
                _log(
                    f"would_enrich  {artist} — {title}  →  bp:{meta['beatport_id']}  score={score:.2f}",
                    f"[green]would enrich:[/green] {artist} — {title}  →  {meta['beatport_link']}  (score={score:.2f})",
                )
                for v_title, v_artist, v_match, v_score in split_extras:
                    v_meta = _bp_meta(v_match)
                    _log(
                        f"would_enrich  {v_artist} — {v_title}  →  bp:{v_meta['beatport_id']}  score={v_score:.2f}  [mashup split]",
                    )
                counts["found"] += 1
                counts["mashup_extra"] += len(split_extras)
                continue

            # Fetch full Beatport catalog detail before saving so the lean row in
            # enriched_tracks gets label/ISRC/sub_genre/etc. on the initial INSERT.
            extras = _fetch_extras(beatport, meta["beatport_id"])
            adapter.save_enriched(track_id, meta, extras)
            seen_base_titles[bk] = meta["beatport_id"]

            counts["found"] += 1
            _log(
                f"enriched  {artist} — {title}  →  bp:{meta['beatport_id']}  score={score:.2f}",
                f"[green]enriched:[/green] {artist} — {title}  →  {meta['beatport_link']}",
            )

            # Enrich additional mashup components as new source rows so both sides
            # of the mashup end up in enriched_tracks.
            for v_title, v_artist, v_match, v_score in split_extras:
                v_bk = _base_key(v_artist, v_title)
                if v_bk in seen_base_titles:
                    continue
                v_meta = _bp_meta(v_match)
                v_extras = _fetch_extras(beatport, v_meta["beatport_id"])
                new_id = adapter.insert_extra(v_artist, v_title, track["source"])
                adapter.save_enriched(new_id, v_meta, v_extras)
                seen_base_titles[v_bk] = v_meta["beatport_id"]
                counts["mashup_extra"] += 1
                _log(
                    f"enriched  {v_artist} — {v_title}  →  bp:{v_meta['beatport_id']}  score={v_score:.2f}  [mashup split]",
                    f"[green]enriched:[/green] {v_artist} — {v_title}  →  {v_meta['beatport_link']}  [mashup split]",
                )

    http_client.close()

    if not dry_run:
        adapter.finish_run(
            run_id,
            seen=counts["seen"],
            found=counts["found"] + counts["mashup_extra"],
            not_found=counts["not_found"],
            fuzzy_miss=counts["fuzzy_miss"],
            duplicate=counts["duplicate"],
        )

    summary = [
        f"--- enrich {'(dry run) ' if dry_run else ''}complete ---",
        f"tracks_seen:   {counts['seen']}",
        f"enriched:      {counts['found']}",
        f"duplicate:     {counts['duplicate']}",
        f"skipped_id:    {counts['skipped_id']}",
        f"no_results:    {counts['not_found']}",
        f"fuzzy_miss:    {counts['fuzzy_miss']}",
        f"search_errors: {counts['failed']}",
        f"mashup_extra:  {counts['mashup_extra']}",
        f"total_rows:    {counts['found'] + counts['mashup_extra']}",
    ]
    for line in summary:
        log_file.write(line + "\n")
    log_file.close()

    console.print()
    console.print(f"[bold]Enrich {'(dry run) ' if dry_run else ''}complete[/bold]")
    console.print(f"  Seen:          {counts['seen']}")
    console.print(f"  Enriched:      {counts['found']}")
    if counts["duplicate"]:
        console.print(f"  Duplicate:     {counts['duplicate']}")
    if counts["skipped_id"]:
        console.print(f"  Skipped ID:    {counts['skipped_id']}")
    console.print(f"  No results:    {counts['not_found']}")
    console.print(f"  Fuzzy miss:    {counts['fuzzy_miss']}")
    console.print(f"  Search errors: {counts['failed']}")
    if counts["mashup_extra"]:
        console.print(f"  Mashup extra:  {counts['mashup_extra']}  [dim](new rows from mashup splits)[/dim]")
        console.print(f"  Total rows:    {counts['found'] + counts['mashup_extra']}")
    console.print(f"[dim]Log: {log_path}[/dim]")
