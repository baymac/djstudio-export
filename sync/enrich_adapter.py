"""`dj enrich --sync` — drives the shared enrich engine over `sync_tracks`.

This is the sync-side adapter for `enrich.engine.run_enrich_engine`. It reads
candidates from the flat `sync_tracks` capture table, writes matches into the one
deduped `enriched_tracks` table (via `detect.db.upsert_enriched_values`), and records
the back-link (`sync_tracks.enriched_beatport_id`) on each source row. The matching
loop itself is 100% shared with `dj enrich --detect`.
"""
from __future__ import annotations

from detect import db as detect_db
from enrich.engine import run_enrich_engine
from sync import db as sync_db


class SyncAdapter:
    """Adapter over `sync_tracks` — backs `dj enrich --sync`."""

    name = "Sync enrich"

    def load_candidates(self, retry_misses: bool) -> list:
        return sync_db.get_retry_sync_tracks() if retry_misses else sync_db.get_unenriched_sync_tracks()

    def secret_count(self) -> int:
        return 0

    def mark_secret(self, row_id: int) -> None:
        sync_db.mark_sync_miss(row_id, "secret")

    def mark_miss(self, row_id: int, outcome: str) -> None:
        sync_db.mark_sync_miss(row_id, outcome)

    def seen_pairs(self) -> list:
        # Shared dedup target: the one enriched_tracks table.
        return detect_db.get_enriched_artist_titles()

    def link_existing(self, row_id: int, beatport_id: int) -> bool:
        # The enriched row for beatport_id already exists (it seeded seen_pairs).
        sync_db.mark_sync_duplicate(row_id, beatport_id)
        return True

    def save_enriched(self, row_id: int, meta: dict, extras: dict) -> None:
        row = sync_db.get_sync_track(row_id)
        artist = row["artist"] if row else None
        title = row["title"] if row else None
        apple_url = (row["native_url"] if row and row["app"] == "apple_music" else None)
        detect_db.upsert_enriched_values(meta, artist, title, extras=extras, apple_url=apple_url)
        sync_db.mark_sync_enriched(row_id, meta.get("beatport_id"))

    def insert_extra(self, artist: str, title: str, source: str) -> int:
        # `source` is the app alias carried through from the candidate row.
        return sync_db.insert_sync_track(source, artist=artist, title=title)

    def start_run(self) -> int:
        return detect_db.start_enrich_run()

    def finish_run(self, run_id, seen, found, not_found, fuzzy_miss, duplicate) -> None:
        detect_db.finish_enrich_run(
            run_id, seen=seen, found=found, not_found=not_found,
            fuzzy_miss=fuzzy_miss, duplicate=duplicate,
        )


def run_sync_enrich(
    *,
    dry_run: bool,
    limit: int,
    verbose: bool,
    threshold: float,
    retry_misses: bool,
) -> None:
    run_enrich_engine(
        SyncAdapter(),
        dry_run=dry_run, limit=limit, verbose=verbose,
        threshold=threshold, retry_misses=retry_misses,
    )
