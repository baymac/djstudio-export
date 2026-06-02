"""Wire `dj detect ...` argparse subparsers — ported from typer track-detect CLI."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import re
import subprocess
import sys
import tempfile
import time
import warnings

from caffeinate import caffeinate

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub")

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from .instagram import (
    build_client,
    download_file,
    fetch_media,
    fetch_pinned_comment,
    fetch_top_comments,
    video_resources,
)
from .db import (
    create_session,
    delete_session,
    end_session,
    find_session,
    infer_last_position,
    insert_track,
    insert_tracks,
    list_sessions,
    migrate,
    remove_tracks_from_session,
    tracks_for_session,
    update_session_progress,
    upsert_shazam_slice,
)
from . import db as detect_db
from .parser import has_track_info, parse_tracks
from .reddit import extract_from_text as reddit_extract_from_text, open_editor_for_post as reddit_open_editor
from .topdjmixes import (
    extract_from_text as topdjmixes_extract_from_text,
    open_editor_for_post as topdjmixes_open_editor,
)
from .tracklists1001 import (
    extract_from_text as tracklists1001_extract_from_text,
    extract_title_from_text as tracklists1001_extract_title,
    open_editor_for_url as tracklists1001_open_editor,
)
from .tracklists1001_api import fetch_tracklist_text as tracklists1001_fetch
from .text import extract_from_text as text_extract_from_text, open_editor_for_session as text_open_editor
from .shazam import RECOGNIZE_TIMEOUT, format_result, recognize_file

load_dotenv()

from paths import DETECT_CONFIG_FILE as CONFIG_FILE
console = Console()


def _confirm(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {hint}: ").strip().lower()
    except KeyboardInterrupt:
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def _load_saved_credentials(service: str = "instagram") -> tuple[str, str] | tuple[None, None]:
    if not CONFIG_FILE.exists():
        return None, None
    data = json.loads(CONFIG_FILE.read_text())
    if service in data and isinstance(data[service], dict):
        return data[service].get("username"), data[service].get("password")
    if service == "instagram" and "username" in data:
        return data.get("username"), data.get("password")
    return None, None


def _save_credentials(username: str, password: str, service: str = "instagram") -> None:
    data: dict = {}
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text())
    if "username" in data and service not in data:
        data["instagram"] = {"username": data.pop("username"), "password": data.pop("password", "")}
    data[service] = {"username": username, "password": password}
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data))
    CONFIG_FILE.chmod(0o600)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _render_text_tracks(tracks: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=4)
    table.add_column("Artist", min_width=22)
    table.add_column("Title", min_width=28)
    for t in tracks:
        table.add_row(str(t.get("position", "")), t.get("artist", "—"), t.get("title", "—"))
    console.print(table)


def _render_shazam_tracks(tracks: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Slide", style="dim", width=6)
    table.add_column("Artist", min_width=22)
    table.add_column("Title", min_width=28)
    table.add_column("Apple Music", min_width=40)
    for t in tracks:
        table.add_row(
            str(t.get("position", "")), t.get("artist", "—"), t.get("title", "—"),
            t.get("apple_music_url") or "—",
        )
    console.print(table)


_MIX_SUFFIX_RE = re.compile(
    r"\s*[\(\-]\s*(extended|original|radio|club|instrumental|acapella|vip|dub|reprise)"
    r"[\s\w]*\s*(?:mix|edit|version|remix|rework)?\s*[\)\s]*$",
    re.IGNORECASE,
)


def _base_title(title: str) -> str:
    return _MIX_SUFFIX_RE.sub("", title).strip().lower()


def _fmt_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _render_mix_tracks(tracks: list[dict]) -> None:
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Time", style="dim", width=8)
    table.add_column("Artist", min_width=22)
    table.add_column("Title", min_width=28)
    table.add_column("Apple Music", min_width=40)
    for t in tracks:
        pos = t.get("position")
        table.add_row(
            _fmt_time(pos) if isinstance(pos, int) else "—",
            t.get("artist", "—"), t.get("title", "—"),
            t.get("apple_music_url") or "—",
        )
    console.print(table)


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — Instagram
# ──────────────────────────────────────────────────────────────────────────────


def _challenge_handler(username: str, choice: int) -> str:
    method = "email" if choice == 1 else "SMS/phone"
    console.print(f"\n[yellow]Instagram verification required.[/yellow] Check your {method} for a code.")
    return input("Verification code: ")


def _two_factor_handler() -> str:
    console.print("\n[yellow]Two-factor authentication required.[/yellow]")
    return input("2FA code: ")


async def _run(
    url: str,
    username: str,
    password: str,
    output: Optional[str],
    json_output: bool,
    dry_run: bool = False,
) -> None:
    console.print("[dim]Logging into Instagram…[/dim]")
    try:
        cl = build_client(username, password,
                          challenge_handler=_challenge_handler,
                          two_factor_handler=_two_factor_handler)
    except Exception as exc:
        console.print(f"[red]Login failed:[/red] {exc}")
        sys.exit(1)
    console.print("[green]✓[/green] Logged in")

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")

    with console.status("[bold green]Fetching post…"):
        try:
            media = fetch_media(cl, url)
        except Exception as exc:
            console.print(f"[red]Could not fetch post:[/red] {exc}")
            sys.exit(1)

    media_type_label = {1: "photo", 2: "video", 8: "carousel"}.get(media.media_type, str(media.media_type))
    console.print(f"[green]✓[/green] Post [dim]{media.pk}[/dim] · type: {media_type_label}")

    caption: str = media.caption_text or ""
    tracks: list[dict] = []
    source = ""

    if caption:
        preview = caption[:180].replace("\n", " ")
        console.print(f"\n[dim]Caption:[/dim] {preview}{'…' if len(caption) > 180 else ''}")
        if has_track_info(caption):
            tracks = parse_tracks(caption)
            source = "caption"

    if not tracks:
        with console.status("[bold green]Checking comments…"):
            pinned = fetch_pinned_comment(cl, str(media.pk))
            comment_text = ""
            if pinned:
                comment_text = pinned.text or ""
                console.print(f"[dim]Pinned comment:[/dim] {comment_text[:180]}")
            else:
                top = fetch_top_comments(cl, str(media.pk), n=5)
                for c in top:
                    if has_track_info(c.text or ""):
                        comment_text = c.text
                        console.print(f"[dim]Comment with tracks:[/dim] {comment_text[:180]}")
                        break

        if comment_text and has_track_info(comment_text):
            tracks = parse_tracks(comment_text)
            source = "comment"

    if tracks:
        console.print(f"\n[bold]Found {len(tracks)} track(s) from {source}:[/bold]")
        _render_text_tracks(tracks)
    else:
        console.print("\n[yellow]No track list found in text — falling back to Shazam audio recognition…[/yellow]")
        tracks = await _shazam_slides(cl, media)
        source = "shazam"
        if tracks:
            console.print(f"\n[bold]Identified {len(tracks)} track(s) via Shazam:[/bold]")
            _render_shazam_tracks(tracks)
        else:
            console.print("[red]Could not identify any tracks.[/red]")

    if tracks:
        shortcode = url.split("/p/")[-1].split("/")[0].split("?")[0]
        if not dry_run:
            session_id = create_session("instagram", url, shortcode, caption=caption or None)
            insert_tracks(tracks, source="instagram", session_id=session_id)
            console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")
        else:
            console.print("\n[yellow](dry run — nothing saved)[/yellow]")

    if json_output:
        console.print_json(json.dumps(tracks, ensure_ascii=False))

    if output:
        Path(output).write_text(json.dumps(tracks, indent=2, ensure_ascii=False))
        console.print(f"\n[green]✓[/green] Saved to {output}")


async def _shazam_slides(cl, media) -> list[dict]:
    videos = video_resources(media)
    if not videos:
        console.print("[yellow]Post has no video slides to analyze.[/yellow]")
        return []

    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, resource in enumerate(videos, start=1):
            video_url = str(getattr(resource, "video_url", "") or "")
            if not video_url:
                continue

            dest = str(Path(tmpdir) / f"slide_{i}.mp4")
            console.print(f"  Slide {i}: [dim]downloading…[/dim]")
            try:
                download_file(video_url, dest)
            except Exception as exc:
                console.print(f"  Slide {i}: [red]download failed — {exc}[/red]")
                continue

            console.print(f"  Slide {i}: [dim]recognizing…[/dim]")
            try:
                raw = await recognize_file(dest)
                track = format_result(raw)
            except Exception as exc:
                console.print(f"  Slide {i}: [red]Shazam error — {exc}[/red]")
                continue

            if track.get("title"):
                track["position"] = i
                results.append(track)
                am = track.get("apple_music_url") or "no Apple Music link"
                console.print(f"  Slide {i}: [green]{track['artist']} — {track['title']}[/green]  {am}")
            else:
                console.print(f"  Slide {i}: [yellow]not recognized[/yellow]")

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — Radio
# ──────────────────────────────────────────────────────────────────────────────


async def _run_radio(url: str, *, interval: int, capture_s: int, duration_min: int, cooldown: int, dry_run: bool = False) -> None:
    from .radio import capture_chunk, resolve_station

    with console.status("Resolving stream URL…"):
        try:
            stream_url, station_name = resolve_station(url)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    console.print(f"[green]✓[/green] Station: [bold]{station_name}[/bold]")
    console.print(f"  Stream:  [dim]{stream_url}[/dim]")

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
        session_id = -1
    else:
        session_id = create_session("radio", stream_url, station_name)
        console.print(f"  Session [bold]#{session_id}[/bold] started")

    if duration_min:
        console.print(
            f"  Monitoring for [bold]{duration_min} min[/bold] "
            f"(capture: {capture_s}s every {interval}s, cooldown: {cooldown}s)"
        )
    else:
        console.print(
            f"  Press [bold]Ctrl+C[/bold] to stop  "
            f"(capture: {capture_s}s every {interval}s, cooldown: {cooldown}s)"
        )

    recent: dict[str, float] = {}
    total_checked = 0
    total_saved = 0
    stop_at = time.monotonic() + duration_min * 60 if duration_min else None
    last_saved_id: int | None = None
    last_saved_mono: float = 0.0
    CONSECUTIVE_GAP = 30.0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            iteration = 0
            while True:
                if stop_at and time.monotonic() >= stop_at:
                    break

                iteration += 1
                t_start = time.monotonic()
                loop = asyncio.get_running_loop()
                track: dict = {}
                chunk_path = str(Path(tmpdir) / f"chunk_{iteration}.mp3")

                capture_failed = False
                with Progress(
                    SpinnerColumn(),
                    TextColumn(f"  [dim][{iteration}] Capturing[/dim]"),
                    BarColumn(bar_width=28),
                    TextColumn("[dim]{task.completed:.0f}/{task.total:.0f}s[/dim]"),
                    TimeRemainingColumn(),
                    console=console,
                    transient=True,
                ) as prog:
                    task_id = prog.add_task("", total=float(capture_s))
                    capture_future = loop.run_in_executor(
                        None, capture_chunk, stream_url, capture_s, chunk_path
                    )
                    t0 = time.monotonic()
                    while not capture_future.done():
                        prog.update(task_id, completed=min(time.monotonic() - t0, float(capture_s)))
                        await asyncio.sleep(0.2)
                    try:
                        await capture_future
                    except subprocess.CalledProcessError as exc:
                        capture_failed = True
                        stderr = (exc.stderr or b"").decode(errors="replace").strip()
                        last_line = stderr.splitlines()[-1] if stderr else "unknown error"
                        console.print(f"  [{iteration}] [red]Capture failed:[/red] {last_line}")
                    except subprocess.TimeoutExpired:
                        capture_failed = True
                        console.print(f"  [{iteration}] [red]Capture timed out[/red]")

                if capture_failed:
                    await asyncio.sleep(max(0, interval - (time.monotonic() - t_start)))
                    continue

                slice_size = 10
                windows: list[tuple[str, str]] = [
                    (chunk_path, f"[{iteration}] full {capture_s}s"),
                ]
                for start in range(0, capture_s, slice_size):
                    slice_path = str(Path(tmpdir) / f"chunk_{iteration}_{start}s.mp3")
                    windows.append((slice_path, f"[{iteration}] slice {start}–{start + slice_size}s"))

                from .radio import slice_audio
                for idx, (audio_path, label) in enumerate(windows):
                    if idx > 0:
                        start = (idx - 1) * slice_size
                        try:
                            slice_audio(chunk_path, start, slice_size, audio_path)
                        except subprocess.CalledProcessError:
                            console.print(f"  {label} [red]Slice failed[/red]")
                            continue

                    try:
                        with console.status(f"  [dim]{label} Recognizing…[/dim]"):
                            raw = await asyncio.wait_for(recognize_file(audio_path), timeout=30.0)
                        track = format_result(raw)
                    except asyncio.TimeoutError:
                        console.print(f"  {label} [yellow]Shazam timeout ({RECOGNIZE_TIMEOUT}s)[/yellow]")
                        break
                    except Exception as exc:
                        console.print(f"  {label} [yellow]Shazam error ({type(exc).__name__}): {exc}[/yellow]")
                        break

                    total_checked += 1

                    if track.get("title"):
                        break

                    if idx < len(windows) - 1:
                        console.print(f"  [dim]{label} not recognized — trying shorter slice…[/dim]")
                    else:
                        console.print(f"  [dim]{label} not recognized[/dim]")

                if track.get("title"):
                    key = track.get("shazam_key") or f"{track.get('artist')}:{track.get('title')}"
                    now_mono = time.monotonic()
                    last_seen = recent.get(key)

                    if last_seen is not None and (now_mono - last_seen) < cooldown:
                        remaining = int(cooldown - (now_mono - last_seen))
                        console.print(
                            f"  [dim]{track['artist']} — {track['title']}"
                            f"  (still playing, cooldown {remaining}s remaining)[/dim]"
                        )
                    else:
                        recent[key] = now_mono
                        if not dry_run:
                            new_id = insert_track(track, source="radio", session_id=session_id)
                            last_saved_id = new_id
                            last_saved_mono = now_mono
                        total_saved += 1
                        am = track.get("apple_music_url") or ""
                        console.print(
                            f"  [green bold]NEW[/green bold]  "
                            f"[bold]{track['artist']}[/bold] — {track['title']}"
                            + (f"  [dim]{am}[/dim]" if am else "")
                        )

                elapsed = time.monotonic() - t_start
                sleep_for = max(0.0, interval - elapsed)
                if sleep_for > 1:
                    console.print(f"  [dim]Next check in {sleep_for:.0f}s…[/dim]")
                    await asyncio.sleep(sleep_for)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        if not dry_run:
            end_session(session_id)
        footer = "[yellow](dry run — nothing saved)[/yellow]" if dry_run else f"Session #{session_id} ended."
        console.print(
            f"\n[bold]{footer}[/bold]  "
            f"Checked {total_checked} windows, saved [green]{total_saved}[/green] new tracks."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — Mixcloud
# ──────────────────────────────────────────────────────────────────────────────


async def _run_mixcloud(
    url: str,
    username: str | None,
    password: str | None,
    scan_interval: int,
    capture_s: int,
    output: str | None,
    json_output: bool,
    resume_session_id: int | None = None,
    resume_from: int = 0,
    dry_run: bool = False,
) -> None:
    from .mixcloud import audio_duration, download_mix, resolve_mix
    from .radio import slice_audio

    with console.status("Resolving mix info…"):
        try:
            mix_title, uploader, duration = resolve_mix(url, username, password)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    console.print(f"[green]✓[/green] Mix: [bold]{mix_title}[/bold]")
    if uploader:
        console.print(f"  Uploader: [dim]{uploader}[/dim]")
    if duration:
        n_checks = max(1, duration // scan_interval)
        console.print(
            f"  Duration: [dim]{_fmt_time(duration)}[/dim]  "
            f"→ ~{n_checks} slices (every {scan_interval}s, {capture_s}s each)"
        )

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
        session_id = -1
        seen_keys: set[str] = set()
        seen_base_keys: set[str] = set()
        all_tracks: list[dict] = []
    elif resume_session_id is not None:
        session_id = resume_session_id
        console.print(
            f"  [yellow]Resuming session [bold]#{session_id}[/bold] "
            f"from {_fmt_time(resume_from)}[/yellow]"
        )
        prior_tracks = tracks_for_session(session_id)
        seen_keys = {
            r["shazam_key"] or f"{r['artist']}:{r['title']}"
            for r in prior_tracks if r["shazam_key"] or r["title"]
        }
        seen_base_keys = {
            f"{r['artist']}:{_base_title(r['title'])}"
            for r in prior_tracks if r["title"]
        }
        all_tracks = [dict(r) for r in prior_tracks]
    else:
        session_id = create_session("mixcloud", url, mix_title, uploader or None, duration)
        console.print(f"  Session [bold]#{session_id}[/bold] started")
        seen_keys = set()
        seen_base_keys = set()
        all_tracks = []

    total_checked = 0
    total_saved = 0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            console.print("")
            with console.status("[bold green]Downloading mix (may take a minute)…[/bold green]"):
                try:
                    mix_path = download_mix(url, tmpdir, username, password)
                except RuntimeError as exc:
                    console.print(f"[red]Download failed:[/red] {exc}")
                    sys.exit(1)

            console.print(f"[green]✓[/green] Downloaded: [dim]{mix_path.name}[/dim]")

            if not duration:
                duration = audio_duration(str(mix_path))
                if duration:
                    n_checks = max(1, duration // scan_interval)
                    console.print(
                        f"  Duration (from file): [dim]{_fmt_time(duration)}[/dim]  "
                        f"→ ~{n_checks} slices"
                    )

            all_positions = list(range(0, max(duration, 1), scan_interval))
            positions = [p for p in all_positions if p > resume_from] if resume_from else all_positions
            total_positions = len(positions)
            skipped = len(all_positions) - total_positions

            if skipped:
                console.print(f"\nSkipping {skipped} already-scanned position(s), scanning {total_positions} remaining…\n")
            else:
                console.print(f"\nScanning {total_positions} position(s)…\n")

            for i, pos in enumerate(positions, 1):
                slice_path = str(Path(tmpdir) / f"slice_{i}.mp3")
                label = f"[{i}/{total_positions}] @{_fmt_time(pos)}"

                try:
                    slice_audio(str(mix_path), pos, capture_s, slice_path)
                except subprocess.CalledProcessError:
                    console.print(f"  {label} [red]slice failed[/red]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                try:
                    with console.status(f"  [dim]{label} Recognizing…[/dim]"):
                        raw = await recognize_file(slice_path)
                    track = format_result(raw)
                except asyncio.TimeoutError:
                    console.print(f"  {label} [yellow]Shazam timeout ({RECOGNIZE_TIMEOUT}s)[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue
                except Exception as exc:
                    console.print(f"  {label} [yellow]Shazam error: {exc}[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                total_checked += 1
                if not dry_run:
                    update_session_progress(session_id, pos)

                if not track.get("title"):
                    console.print(f"  [dim]{label} not recognized[/dim]")
                    continue

                key = track.get("shazam_key") or f"{track.get('artist')}:{track.get('title')}"
                base_key = f"{track.get('artist')}:{_base_title(track.get('title', ''))}"
                if key in seen_keys or base_key in seen_base_keys:
                    console.print(f"  [dim]{label} {track['artist']} — {track['title']} (duplicate)[/dim]")
                    continue

                seen_keys.add(key)
                seen_base_keys.add(base_key)
                track["position"] = pos
                if not dry_run:
                    insert_track(track, source="mixcloud", session_id=session_id)
                total_saved += 1
                all_tracks.append(track)
                am = track.get("apple_music_url") or ""
                console.print(
                    f"  [green bold]FOUND[/green bold]  {label}  "
                    f"[bold]{track['artist']}[/bold] — {track['title']}"
                    + (f"  [dim]{am}[/dim]" if am else "")
                )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        if not dry_run:
            end_session(session_id)
        footer = "[yellow](dry run — nothing saved)[/yellow]" if dry_run else f"Session #{session_id} complete."
        console.print(
            f"\n[bold]{footer}[/bold]  "
            f"Checked {total_checked} slices, found [green]{total_saved}[/green] unique tracks."
        )

    if all_tracks:
        console.print("\n[bold]Tracklist:[/bold]")
        _render_mix_tracks(all_tracks)

    if json_output:
        console.print_json(json.dumps(all_tracks, ensure_ascii=False))

    if output:
        Path(output).write_text(json.dumps(all_tracks, indent=2, ensure_ascii=False))
        console.print(f"\n[green]✓[/green] Saved to {output}")


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — YouTube
# ──────────────────────────────────────────────────────────────────────────────


async def _run_youtube(
    url: str,
    scan_interval: int,
    capture_s: int,
    output: str | None,
    json_output: bool,
    resume_session_id: int | None = None,
    resume_from: int = 0,
    dry_run: bool = False,
) -> None:
    from .youtube import audio_duration, download_video, resolve_video
    from .radio import slice_audio

    with console.status("Resolving video info…"):
        try:
            video_title, uploader, duration = resolve_video(url)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    console.print(f"[green]✓[/green] Video: [bold]{video_title}[/bold]")
    if uploader:
        console.print(f"  Uploader: [dim]{uploader}[/dim]")
    if duration:
        n_checks = max(1, duration // scan_interval)
        console.print(
            f"  Duration: [dim]{_fmt_time(duration)}[/dim]  "
            f"→ ~{n_checks} slices (every {scan_interval}s, {capture_s}s each)"
        )

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
        session_id = -1
        seen_keys: set[str] = set()
        seen_base_keys: set[str] = set()
        all_tracks: list[dict] = []
    elif resume_session_id is not None:
        session_id = resume_session_id
        console.print(
            f"  [yellow]Resuming session [bold]#{session_id}[/bold] "
            f"from {_fmt_time(resume_from)}[/yellow]"
        )
        prior_tracks = tracks_for_session(session_id)
        seen_keys = {
            r["shazam_key"] or f"{r['artist']}:{r['title']}"
            for r in prior_tracks if r["shazam_key"] or r["title"]
        }
        seen_base_keys = {
            f"{r['artist']}:{_base_title(r['title'])}"
            for r in prior_tracks if r["title"]
        }
        all_tracks = [dict(r) for r in prior_tracks]
    else:
        session_id = create_session("youtube", url, video_title, uploader or None, duration)
        console.print(f"  Session [bold]#{session_id}[/bold] started")
        seen_keys = set()
        seen_base_keys = set()
        all_tracks = []

    total_checked = 0
    total_saved = 0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            console.print("")
            with console.status("[bold green]Downloading video audio (may take a minute)…[/bold green]"):
                try:
                    video_path = download_video(url, tmpdir)
                except RuntimeError as exc:
                    console.print(f"[red]Download failed:[/red] {exc}")
                    sys.exit(1)

            console.print(f"[green]✓[/green] Downloaded: [dim]{video_path.name}[/dim]")

            if not duration:
                duration = audio_duration(str(video_path))
                if duration:
                    n_checks = max(1, duration // scan_interval)
                    console.print(
                        f"  Duration (from file): [dim]{_fmt_time(duration)}[/dim]  "
                        f"→ ~{n_checks} slices"
                    )

            all_positions = list(range(0, max(duration, 1), scan_interval))
            positions = [p for p in all_positions if p > resume_from] if resume_from else all_positions
            total_positions = len(positions)
            skipped = len(all_positions) - total_positions

            if skipped:
                console.print(f"\nSkipping {skipped} already-scanned position(s), scanning {total_positions} remaining…\n")
            else:
                console.print(f"\nScanning {total_positions} position(s)…\n")

            for i, pos in enumerate(positions, 1):
                slice_path = str(Path(tmpdir) / f"slice_{i}.mp3")
                label = f"[{i}/{total_positions}] @{_fmt_time(pos)}"

                try:
                    slice_audio(str(video_path), pos, capture_s, slice_path)
                except subprocess.CalledProcessError:
                    console.print(f"  {label} [red]slice failed[/red]")
                    if not dry_run:
                        upsert_shazam_slice(session_id, pos, "slice_failed")
                        update_session_progress(session_id, pos)
                    continue

                try:
                    with console.status(f"  [dim]{label} Recognizing…[/dim]"):
                        raw = await recognize_file(slice_path)
                    track = format_result(raw)
                except asyncio.TimeoutError:
                    console.print(f"  {label} [yellow]Shazam timeout ({RECOGNIZE_TIMEOUT}s)[/yellow]")
                    if not dry_run:
                        upsert_shazam_slice(session_id, pos, "timeout")
                        update_session_progress(session_id, pos)
                    continue
                except Exception as exc:
                    console.print(f"  {label} [yellow]Shazam error: {exc}[/yellow]")
                    if not dry_run:
                        upsert_shazam_slice(session_id, pos, "error")
                        update_session_progress(session_id, pos)
                    continue

                total_checked += 1
                if not dry_run:
                    update_session_progress(session_id, pos)

                if not track.get("title"):
                    console.print(f"  [dim]{label} not recognized[/dim]")
                    if not dry_run:
                        upsert_shazam_slice(session_id, pos, "not_recognized")
                    continue

                key = track.get("shazam_key") or f"{track.get('artist')}:{track.get('title')}"
                base_key = f"{track.get('artist')}:{_base_title(track.get('title', ''))}"
                if key in seen_keys or base_key in seen_base_keys:
                    console.print(f"  [dim]{label} {track['artist']} — {track['title']} (duplicate)[/dim]")
                    if not dry_run:
                        upsert_shazam_slice(session_id, pos, "duplicate",
                                            artist=track.get("artist"), title=track.get("title"),
                                            shazam_key=track.get("shazam_key"))
                    continue

                seen_keys.add(key)
                seen_base_keys.add(base_key)
                track["position"] = pos
                if not dry_run:
                    insert_track(track, source="youtube", session_id=session_id)
                    am = track.get("apple_music_url") or ""
                    upsert_shazam_slice(session_id, pos, "found",
                                        artist=track.get("artist"), title=track.get("title"),
                                        shazam_key=track.get("shazam_key"), apple_music_url=am or None)
                else:
                    am = track.get("apple_music_url") or ""
                total_saved += 1
                all_tracks.append(track)
                console.print(
                    f"  [green bold]FOUND[/green bold]  {label}  "
                    f"[bold]{track['artist']}[/bold] — {track['title']}"
                    + (f"  [dim]{am}[/dim]" if am else "")
                )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        if not dry_run:
            end_session(session_id)
        footer = "[yellow](dry run — nothing saved)[/yellow]" if dry_run else f"Session #{session_id} complete."
        console.print(
            f"\n[bold]{footer}[/bold]  "
            f"Checked {total_checked} slices, found [green]{total_saved}[/green] unique tracks."
        )

    if all_tracks:
        console.print("\n[bold]Tracklist:[/bold]")
        _render_mix_tracks(all_tracks)

    if json_output:
        console.print_json(json.dumps(all_tracks, ensure_ascii=False))

    if output:
        Path(output).write_text(json.dumps(all_tracks, indent=2, ensure_ascii=False))
        console.print(f"\n[green]✓[/green] Saved to {output}")


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — SoundCloud
# ──────────────────────────────────────────────────────────────────────────────

# Single SoundCloud tracks shorter than this are treated as standalone songs
# (metadata save only). Longer ones are assumed to be DJ mixes and Shazam-scanned.
SOUNDCLOUD_SONG_DURATION_S = 15 * 60  # 15 minutes


def _run_soundcloud_set(url: str, dry_run: bool = False) -> None:
    """Set URL → enumerate child tracks via metadata, save each one."""
    from .soundcloud import list_set_tracks

    with console.status("Enumerating set tracks…"):
        try:
            tracks, dropped = list_set_tracks(url)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    if not tracks:
        console.print("[yellow]No tracks found in this set.[/yellow]")
        sys.exit(0)

    set_slug = url.rstrip("/").split("/")[-1].replace("-", " ").title() or "SoundCloud Set"
    skip_note = (
        f", [yellow]{dropped}[/yellow] anonymized/empty skipped" if dropped else ""
    )
    console.print(
        f"[green]✓[/green] Set: [bold]{set_slug}[/bold]  "
        f"([cyan]{len(tracks)}[/cyan] tracks{skip_note}, no audio download)"
    )

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
    else:
        prior = find_session(url)
        if prior:
            n_existing = len(tracks_for_session(prior["id"]))
            scanned_on = prior["started_at"][:10]
            console.print(
                f"\n[dim]Already enumerated on {scanned_on} "
                f"(session #{prior['id']}, {n_existing} track(s)).[/dim]\n"
            )
            if not _confirm("Re-enumerate?", default=False):
                sys.exit(0)

        total_duration = sum(t.get("duration") or 0 for t in tracks)
        session_id = create_session("soundcloud", url, set_slug, set_slug, total_duration)

        insert_tracks(tracks, source="soundcloud", session_id=session_id)
        end_session(session_id)

    t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    t.add_column("#",        style="dim", width=4)
    t.add_column("Artist",   min_width=22)
    t.add_column("Title",    min_width=28)
    t.add_column("Duration", style="dim", width=8)
    for tr in tracks:
        dur = _fmt_time(tr.get("duration") or 0) if tr.get("duration") else "—"
        t.add_row(str(tr["position"]), tr["artist"], tr["title"], dur)
    console.print(t)
    if dry_run:
        console.print("\n[yellow](dry run — nothing saved)[/yellow]")
    else:
        console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")


def _save_soundcloud_song(url: str, raw_title: str, uploader: str, duration: int, dry_run: bool = False) -> None:
    """Single short SoundCloud track → save metadata as one detected_tracks row."""
    from .soundcloud import parse_artist_title
    artist, title = parse_artist_title(raw_title, uploader)

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
    else:
        prior = find_session(url)
        if prior:
            scanned_on = prior["started_at"][:10]
            console.print(
                f"\n[dim]Already saved on {scanned_on} (session #{prior['id']}).[/dim]\n"
            )
            if not _confirm("Save again?", default=False):
                sys.exit(0)

    console.print(
        f"[green]✓[/green] Track: [bold]{artist}[/bold] — {title}  "
        f"[dim]({_fmt_time(duration)})[/dim]"
    )

    if not dry_run:
        session_id = create_session("soundcloud", url, raw_title or title, uploader or None, duration)
        insert_tracks(
            [{"position": 1, "artist": artist, "title": title}],
            source="soundcloud", session_id=session_id,
        )
        end_session(session_id)
        console.print(f"[dim]Saved to DB (session #{session_id})[/dim]")
    else:
        console.print("[yellow](dry run — nothing saved)[/yellow]")


async def _run_soundcloud(
    url: str,
    scan_interval: int,
    capture_s: int,
    output: str | None,
    json_output: bool,
    resume_session_id: int | None = None,
    resume_from: int = 0,
    dry_run: bool = False,
) -> None:
    from .soundcloud import audio_duration, download_mix, resolve_mix
    from .radio import slice_audio

    with console.status("Resolving mix info…"):
        try:
            mix_title, uploader, duration = resolve_mix(url)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    console.print(f"[green]✓[/green] Mix: [bold]{mix_title}[/bold]")
    if uploader:
        console.print(f"  Uploader: [dim]{uploader}[/dim]")
    if duration:
        n_checks = max(1, duration // scan_interval)
        console.print(
            f"  Duration: [dim]{_fmt_time(duration)}[/dim]  "
            f"→ ~{n_checks} slices (every {scan_interval}s, {capture_s}s each)"
        )

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
        session_id = -1
        seen_keys: set[str] = set()
        seen_base_keys: set[str] = set()
        all_tracks: list[dict] = []
    elif resume_session_id is not None:
        session_id = resume_session_id
        console.print(
            f"  [yellow]Resuming session [bold]#{session_id}[/bold] "
            f"from {_fmt_time(resume_from)}[/yellow]"
        )
        prior_tracks = tracks_for_session(session_id)
        seen_keys = {
            r["shazam_key"] or f"{r['artist']}:{r['title']}"
            for r in prior_tracks if r["shazam_key"] or r["title"]
        }
        seen_base_keys = {
            f"{r['artist']}:{_base_title(r['title'])}"
            for r in prior_tracks if r["title"]
        }
        all_tracks = [dict(r) for r in prior_tracks]
    else:
        session_id = create_session("soundcloud", url, mix_title, uploader or None, duration)
        console.print(f"  Session [bold]#{session_id}[/bold] started")
        seen_keys = set()
        seen_base_keys = set()
        all_tracks = []

    total_checked = 0
    total_saved = 0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            console.print("")
            with console.status("[bold green]Downloading mix audio (may take a minute)…[/bold green]"):
                try:
                    mix_path = download_mix(url, tmpdir)
                except RuntimeError as exc:
                    console.print(f"[red]Download failed:[/red] {exc}")
                    sys.exit(1)

            console.print(f"[green]✓[/green] Downloaded: [dim]{mix_path.name}[/dim]")

            if not duration:
                duration = audio_duration(str(mix_path))
                if duration:
                    n_checks = max(1, duration // scan_interval)
                    console.print(
                        f"  Duration (from file): [dim]{_fmt_time(duration)}[/dim]  "
                        f"→ ~{n_checks} slices"
                    )

            all_positions = list(range(0, max(duration, 1), scan_interval))
            positions = [p for p in all_positions if p > resume_from] if resume_from else all_positions
            total_positions = len(positions)
            skipped = len(all_positions) - total_positions

            if skipped:
                console.print(f"\nSkipping {skipped} already-scanned position(s), scanning {total_positions} remaining…\n")
            else:
                console.print(f"\nScanning {total_positions} position(s)…\n")

            for i, pos in enumerate(positions, 1):
                slice_path = str(Path(tmpdir) / f"slice_{i}.mp3")
                label = f"[{i}/{total_positions}] @{_fmt_time(pos)}"

                try:
                    slice_audio(str(mix_path), pos, capture_s, slice_path)
                except subprocess.CalledProcessError:
                    console.print(f"  {label} [red]slice failed[/red]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                try:
                    with console.status(f"  [dim]{label} Recognizing…[/dim]"):
                        raw = await recognize_file(slice_path)
                    track = format_result(raw)
                except asyncio.TimeoutError:
                    console.print(f"  {label} [yellow]Shazam timeout ({RECOGNIZE_TIMEOUT}s)[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue
                except Exception as exc:
                    console.print(f"  {label} [yellow]Shazam error: {exc}[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                total_checked += 1
                if not dry_run:
                    update_session_progress(session_id, pos)

                if not track.get("title"):
                    console.print(f"  [dim]{label} not recognized[/dim]")
                    continue

                key = track.get("shazam_key") or f"{track.get('artist')}:{track.get('title')}"
                base_key = f"{track.get('artist')}:{_base_title(track.get('title', ''))}"
                if key in seen_keys or base_key in seen_base_keys:
                    console.print(f"  [dim]{label} {track['artist']} — {track['title']} (duplicate)[/dim]")
                    continue

                seen_keys.add(key)
                seen_base_keys.add(base_key)
                track["position"] = pos
                if not dry_run:
                    insert_track(track, source="soundcloud", session_id=session_id)
                total_saved += 1
                all_tracks.append(track)
                am = track.get("apple_music_url") or ""
                console.print(
                    f"  [green bold]FOUND[/green bold]  {label}  "
                    f"[bold]{track['artist']}[/bold] — {track['title']}"
                    + (f"  [dim]{am}[/dim]" if am else "")
                )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        if not dry_run:
            end_session(session_id)
        footer = "[yellow](dry run — nothing saved)[/yellow]" if dry_run else f"Session #{session_id} complete."
        console.print(
            f"\n[bold]{footer}[/bold]  "
            f"Checked {total_checked} slices, found [green]{total_saved}[/green] unique tracks."
        )

    if all_tracks:
        console.print("\n[bold]Tracklist:[/bold]")
        _render_mix_tracks(all_tracks)

    if json_output:
        console.print_json(json.dumps(all_tracks, ensure_ascii=False))

    if output:
        Path(output).write_text(json.dumps(all_tracks, indent=2, ensure_ascii=False))
        console.print(f"\n[green]✓[/green] Saved to {output}")


# ──────────────────────────────────────────────────────────────────────────────
# Core async logic — Podbean
# ──────────────────────────────────────────────────────────────────────────────


async def _run_podbean(
    url: str,
    scan_interval: int,
    capture_s: int,
    output: str | None,
    json_output: bool,
    resume_session_id: int | None = None,
    resume_from: int = 0,
    dry_run: bool = False,
) -> None:
    from .podbean import audio_duration, download_episode, resolve_episode
    from .radio import slice_audio

    with console.status("Resolving episode info…"):
        try:
            episode_title, podcast_name, duration = resolve_episode(url)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            sys.exit(1)

    console.print(f"[green]✓[/green] Episode: [bold]{episode_title}[/bold]")
    if podcast_name:
        console.print(f"  Podcast: [dim]{podcast_name}[/dim]")
    if duration:
        n_checks = max(1, duration // scan_interval)
        console.print(
            f"  Duration: [dim]{_fmt_time(duration)}[/dim]  "
            f"→ ~{n_checks} slices (every {scan_interval}s, {capture_s}s each)"
        )

    if dry_run:
        console.print("  [yellow]Dry run — no DB writes[/yellow]")
        session_id = -1
        seen_keys: set[str] = set()
        seen_base_keys: set[str] = set()
        all_tracks: list[dict] = []
    elif resume_session_id is not None:
        session_id = resume_session_id
        console.print(
            f"  [yellow]Resuming session [bold]#{session_id}[/bold] "
            f"from {_fmt_time(resume_from)}[/yellow]"
        )
        prior_tracks = tracks_for_session(session_id)
        seen_keys = {
            r["shazam_key"] or f"{r['artist']}:{r['title']}"
            for r in prior_tracks if r["shazam_key"] or r["title"]
        }
        seen_base_keys = {
            f"{r['artist']}:{_base_title(r['title'])}"
            for r in prior_tracks if r["title"]
        }
        all_tracks = [dict(r) for r in prior_tracks]
    else:
        session_id = create_session("podbean", url, episode_title, podcast_name or None, duration)
        console.print(f"  Session [bold]#{session_id}[/bold] started")
        seen_keys = set()
        seen_base_keys = set()
        all_tracks = []

    total_checked = 0
    total_saved = 0

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            console.print("")
            with console.status("[bold green]Downloading episode (may take a minute)…[/bold green]"):
                try:
                    episode_path = download_episode(url, tmpdir)
                except RuntimeError as exc:
                    console.print(f"[red]Download failed:[/red] {exc}")
                    sys.exit(1)

            console.print(f"[green]✓[/green] Downloaded: [dim]{episode_path.name}[/dim]")

            if not duration:
                duration = audio_duration(str(episode_path))
                if duration:
                    n_checks = max(1, duration // scan_interval)
                    console.print(
                        f"  Duration (from file): [dim]{_fmt_time(duration)}[/dim]  "
                        f"→ ~{n_checks} slices"
                    )

            all_positions = list(range(0, max(duration, 1), scan_interval))
            positions = [p for p in all_positions if p > resume_from] if resume_from else all_positions
            total_positions = len(positions)
            skipped = len(all_positions) - total_positions

            if skipped:
                console.print(f"\nSkipping {skipped} already-scanned position(s), scanning {total_positions} remaining…\n")
            else:
                console.print(f"\nScanning {total_positions} position(s)…\n")

            for i, pos in enumerate(positions, 1):
                slice_path = str(Path(tmpdir) / f"slice_{i}.mp3")
                label = f"[{i}/{total_positions}] @{_fmt_time(pos)}"

                try:
                    slice_audio(str(episode_path), pos, capture_s, slice_path)
                except subprocess.CalledProcessError:
                    console.print(f"  {label} [red]slice failed[/red]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                try:
                    with console.status(f"  [dim]{label} Recognizing…[/dim]"):
                        raw = await recognize_file(slice_path)
                    track = format_result(raw)
                except asyncio.TimeoutError:
                    console.print(f"  {label} [yellow]Shazam timeout ({RECOGNIZE_TIMEOUT}s)[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue
                except Exception as exc:
                    console.print(f"  {label} [yellow]Shazam error: {exc}[/yellow]")
                    if not dry_run:
                        update_session_progress(session_id, pos)
                    continue

                total_checked += 1
                if not dry_run:
                    update_session_progress(session_id, pos)

                if not track.get("title"):
                    console.print(f"  [dim]{label} not recognized[/dim]")
                    continue

                key = track.get("shazam_key") or f"{track.get('artist')}:{track.get('title')}"
                base_key = f"{track.get('artist')}:{_base_title(track.get('title', ''))}"
                if key in seen_keys or base_key in seen_base_keys:
                    console.print(f"  [dim]{label} {track['artist']} — {track['title']} (duplicate)[/dim]")
                    continue

                seen_keys.add(key)
                seen_base_keys.add(base_key)
                track["position"] = pos
                if not dry_run:
                    insert_track(track, source="podbean", session_id=session_id)
                total_saved += 1
                all_tracks.append(track)
                am = track.get("apple_music_url") or ""
                console.print(
                    f"  [green bold]FOUND[/green bold]  {label}  "
                    f"[bold]{track['artist']}[/bold] — {track['title']}"
                    + (f"  [dim]{am}[/dim]" if am else "")
                )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        if not dry_run:
            end_session(session_id)
        footer = "[yellow](dry run — nothing saved)[/yellow]" if dry_run else f"Session #{session_id} complete."
        console.print(
            f"\n[bold]{footer}[/bold]  "
            f"Checked {total_checked} slices, found [green]{total_saved}[/green] unique tracks."
        )

    if all_tracks:
        console.print("\n[bold]Tracklist:[/bold]")
        _render_mix_tracks(all_tracks)

    if json_output:
        console.print_json(json.dumps(all_tracks, ensure_ascii=False))

    if output:
        Path(output).write_text(json.dumps(all_tracks, indent=2, ensure_ascii=False))
        console.print(f"\n[green]✓[/green] Saved to {output}")


def _cmd_fix_session(args) -> None:
    """Compare a confirmed tracklist (stdin) against detected tracks and remove mismatches."""
    import sys
    from difflib import SequenceMatcher
    from .text import extract_from_text, _ID_LINE_RE, _TS_RE, _clean_line, _SEP_RE

    session_id = args.session_id
    threshold = args.threshold
    apply = args.apply

    # ── Load detected tracks ──────────────────────────────────────────────────
    detected = tracks_for_session(session_id)
    if not detected:
        console.print(f"[yellow]No tracks found for session #{session_id}.[/yellow]")
        return

    # ── Read confirmed tracklist from stdin ───────────────────────────────────
    if sys.stdin.isatty():
        console.print(
            f"\n[bold]Paste the confirmed tracklist, then press Ctrl-D when done.[/bold]\n"
            f"[dim]Format: [HH:MM] TITLE - ARTIST   (or ARTIST - TITLE — both work)[/dim]\n"
            f"[dim]Lines starting with 'ID' are skipped.[/dim]\n"
        )
    raw_text = sys.stdin.read()

    # ── Parse confirmed lines (reuse text.py logic + extra ID filter) ─────────
    def _norm(s: str) -> str:
        s = re.sub(r"[\(\[{][^\)\]{}]*[\)\]{}]", " ", s)   # strip bracketed blocks
        s = re.sub(r"[^\w\s]", " ", s.lower())
        return re.sub(r"\s+", " ", s).strip()

    confirmed: list[tuple[str, str]] = []   # (left, right) raw parts — order unknown
    for raw_line in raw_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line or raw_line.startswith("#"):
            continue
        cleaned = _clean_line(raw_line)
        if not cleaned:
            continue
        # Skip pure ID placeholders: "ID" or "ID - ID" or "ID (anything)"
        if re.match(r"^ID\b", cleaned, re.IGNORECASE):
            continue
        m = _SEP_RE.search(cleaned)
        if not m:
            continue
        left = cleaned[: m.start()].strip()
        right = cleaned[m.end() :].strip()
        if not left or not right:
            continue
        # Skip if either side is just "ID"
        if left.upper() == "ID" or right.upper() == "ID":
            continue
        confirmed.append((left, right))

    if not confirmed:
        console.print("[yellow]No confirmed tracks parsed from input.[/yellow]")
        return

    # ── Score each detected track against all confirmed entries ───────────────
    def _match_score(conf_left: str, conf_right: str, det_artist: str, det_title: str) -> float:
        nl, nr = _norm(conf_left), _norm(conf_right)
        na, nt = _norm(det_artist or ""), _norm(det_title or "")
        # Try both orderings: conf as (title, artist) and conf as (artist, title)
        score1 = 0.6 * SequenceMatcher(None, nl, nt).ratio() + 0.4 * SequenceMatcher(None, nr, na).ratio()
        score2 = 0.6 * SequenceMatcher(None, nr, nt).ratio() + 0.4 * SequenceMatcher(None, nl, na).ratio()
        return max(score1, score2)

    # Build score matrix: scores[det_idx][conf_idx]
    scores = [
        [_match_score(cl, cr, d["artist"] or "", d["title"] or "") for (cl, cr) in confirmed]
        for d in detected
    ]

    # Greedy assignment: pair each confirmed entry to its best unmatched detected track
    confirmed_matched = [False] * len(confirmed)
    det_to_conf: dict[int, int] = {}   # det_idx → conf_idx
    det_scores: dict[int, float] = {}  # det_idx → score

    # Collect all (score, det_idx, conf_idx) triples.
    # Tiebreak by det_idx ascending (detected list is already ordered by position,
    # so earlier tracks win when scores are identical).
    triples = sorted(
        [(scores[di][ci], -di, di, ci) for di in range(len(detected)) for ci in range(len(confirmed))],
        reverse=True,
    )
    triples = [(sc, di, ci) for sc, _, di, ci in triples]
    for score, di, ci in triples:
        if di in det_to_conf or confirmed_matched[ci]:
            continue
        if score >= threshold:
            det_to_conf[di] = ci
            confirmed_matched[ci] = True
            det_scores[di] = score

    # ── Build keep / delete lists ─────────────────────────────────────────────
    to_keep = [d for i, d in enumerate(detected) if i in det_to_conf]
    to_delete = [d for i, d in enumerate(detected) if i not in det_to_conf]

    # ── Render diff table ─────────────────────────────────────────────────────
    console.print(f"\n[bold]Session #{session_id} — fix-session diff[/bold]\n")
    t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    t.add_column("Action", width=8)
    t.add_column("ID", style="dim", width=6)
    t.add_column("Artist", min_width=22)
    t.add_column("Title", min_width=26)
    t.add_column("Score", style="dim", width=6)

    for i, d in enumerate(detected):
        if i in det_to_conf:
            sc = f"{det_scores[i]:.2f}"
            t.add_row("[green]KEEP[/green]", str(d["id"]), d["artist"] or "—", d["title"] or "—", sc)
        else:
            best_sc = max(scores[i]) if confirmed else 0.0
            t.add_row("[red]DELETE[/red]", str(d["id"]), d["artist"] or "—", d["title"] or "—",
                      f"{best_sc:.2f}")

    console.print(t)
    console.print()

    unmatched_conf = [(cl, cr) for j, (cl, cr) in enumerate(confirmed) if not confirmed_matched[j]]
    if unmatched_conf:
        console.print("[dim]Confirmed entries with no matching detected track (not added):[/dim]")
        for cl, cr in unmatched_conf:
            console.print(f"  [dim]{cl} - {cr}[/dim]")
        console.print()

    if not to_delete:
        console.print("[green]Nothing to delete — session is already clean.[/green]")
        return

    console.print(f"[bold]{len(to_delete)} track(s) will be removed[/bold] from session #{session_id}.")

    if not apply:
        console.print("\n[dim]Dry-run — pass --apply to commit.[/dim]")
        return

    removed = remove_tracks_from_session(session_id, [d["id"] for d in to_delete])
    console.print(
        f"\n[green]✓[/green] Unlinked {len(to_delete)} track(s) from session #{session_id}; "
        f"{len(removed)} fully deleted from detected_tracks."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Argparse CLI
# ──────────────────────────────────────────────────────────────────────────────


def add_detect_subparser(parent: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Attach `detect` and its subcommands to the parent subparsers."""
    detect_p = parent.add_parser(
        "detect",
        help="Detect tracks from Instagram, radio, Mixcloud, YouTube, Podbean via Shazam",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run dj_cli.py detect instagram https://www.instagram.com/p/XXXXX/
  uv run dj_cli.py detect radio-garden https://radio.garden/listen/kexp/kexp
  uv run dj_cli.py detect mixcloud https://www.mixcloud.com/djname/mix/
  uv run dj_cli.py detect youtube https://www.youtube.com/watch?v=XXXX
  uv run dj_cli.py detect podbean https://www.podbean.com/ew/pb-XXXX
  uv run dj_cli.py detect reddit https://www.reddit.com/r/HypeTracks/comments/XXXXX/
  uv run dj_cli.py detect 1001tracklists https://www.1001tracklists.com/tracklist/XXXXX/
  uv run dj_cli.py detect gems --source beatport --genre "Tech House" --count 10

  (enrich detected tracks afterwards with: uv run dj_cli.py enrich --detect)
""",
    )
    sub = detect_p.add_subparsers(dest="detect_command")

    # instagram
    ig_p = sub.add_parser("instagram", help="Detect tracks from an Instagram post")
    ig_p.add_argument("url", help="Instagram post URL")
    ig_p.add_argument("--username", "-u", default=None,
                      help="Instagram username (or set IG_USERNAME)")
    ig_p.add_argument("--password", "-p", default=None,
                      help="Instagram password (or set IG_PASSWORD)")
    ig_p.add_argument("--output", "-o", default=None, help="Write results to JSON file")
    ig_p.add_argument("--json", "-j", action="store_true", dest="json_output",
                      help="Print results as JSON to stdout")
    ig_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # radio-garden
    rg_p = sub.add_parser("radio-garden", help="Monitor a radio.garden station")
    rg_p.add_argument("url", help="radio.garden station URL")
    rg_p.add_argument("--interval", "-i", type=int, default=60,
                      help="Seconds between Shazam checks (default: 60)")
    rg_p.add_argument("--capture", "-c", type=int, default=30,
                      help="Seconds of audio to capture per check (default: 30)")
    rg_p.add_argument("--duration", "-d", type=int, default=0,
                      help="Total minutes to monitor (0 = run until Ctrl+C)")
    rg_p.add_argument("--cooldown", type=int, default=600,
                      help="Seconds before same track can be saved again (default: 600)")
    rg_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # mixcloud
    mc_p = sub.add_parser("mixcloud", help="Scan a Mixcloud mix and identify tracks")
    mc_p.add_argument("url", help="Mixcloud mix URL")
    mc_p.add_argument("--username", "-u", default=None, help="Mixcloud username")
    mc_p.add_argument("--password", "-p", default=None, help="Mixcloud password")
    mc_p.add_argument("--interval", "-i", type=int, default=60,
                      help="Seconds between Shazam checks (default: 60)")
    mc_p.add_argument("--capture", "-c", type=int, default=30,
                      help="Seconds of audio to capture per check (default: 30)")
    mc_p.add_argument("--output", "-o", default=None, help="Write tracklist to JSON file")
    mc_p.add_argument("--json", "-j", action="store_true", dest="json_output",
                      help="Print tracklist as JSON to stdout")
    mc_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # youtube
    yt_p = sub.add_parser("youtube", help="Scan a YouTube video and identify tracks")
    yt_p.add_argument("url", help="YouTube video URL")
    yt_p.add_argument("--interval", "-i", type=int, default=60,
                      help="Seconds between Shazam checks (default: 60)")
    yt_p.add_argument("--capture", "-c", type=int, default=30,
                      help="Seconds of audio to capture per check (default: 30)")
    yt_p.add_argument("--output", "-o", default=None, help="Write tracklist to JSON file")
    yt_p.add_argument("--json", "-j", action="store_true", dest="json_output",
                      help="Print tracklist as JSON to stdout")
    yt_p.add_argument("--dry-run", action="store_true",
                      help="Run Shazam recognition but skip all DB writes")

    # soundcloud
    sc_p = sub.add_parser("soundcloud", help="Scan a SoundCloud mix and identify tracks")
    sc_p.add_argument("url", help="SoundCloud mix URL (tracking params auto-stripped)")
    sc_p.add_argument("--interval", "-i", type=int, default=60,
                      help="Seconds between Shazam checks (default: 60)")
    sc_p.add_argument("--capture", "-c", type=int, default=30,
                      help="Seconds of audio to capture per check (default: 30)")
    sc_p.add_argument("--output", "-o", default=None, help="Write tracklist to JSON file")
    sc_p.add_argument("--json", "-j", action="store_true", dest="json_output",
                      help="Print tracklist as JSON to stdout")
    sc_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # podbean
    pb_p = sub.add_parser("podbean", help="Scan a Podbean episode and identify tracks")
    pb_p.add_argument("url", help="Podbean episode URL")
    pb_p.add_argument("--interval", "-i", type=int, default=60,
                      help="Seconds between Shazam checks (default: 60)")
    pb_p.add_argument("--capture", "-c", type=int, default=30,
                      help="Seconds of audio to capture per check (default: 30)")
    pb_p.add_argument("--output", "-o", default=None, help="Write tracklist to JSON file")
    pb_p.add_argument("--json", "-j", action="store_true", dest="json_output",
                      help="Print tracklist as JSON to stdout")
    pb_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # reddit
    rd_p = sub.add_parser("reddit", help="Extract tracks from a Reddit text post")
    rd_p.add_argument("url", help="Reddit post URL")
    rd_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # reddit-delete-session
    rd_del_p = sub.add_parser("reddit-delete-session", help="Delete a Reddit session and its tracks")
    rd_del_p.add_argument("session_id", type=int)
    rd_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # topdjmixes
    td_p = sub.add_parser("topdjmixes", help="Extract tracks from a topdjmixes.com mix page")
    td_p.add_argument("url", help="topdjmixes.com mix URL")
    td_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # topdjmixes-delete-session
    td_del_p = sub.add_parser("topdjmixes-delete-session",
                              help="Delete a topdjmixes session and its tracks")
    td_del_p.add_argument("session_id", type=int)
    td_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # 1001tracklists
    tl_p = sub.add_parser("1001tracklists", help="Extract tracks from a 1001tracklists.com tracklist page")
    tl_p.add_argument("url", help="1001tracklists.com tracklist URL")
    tl_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")
    tl_p.add_argument("--paste", action="store_true",
                      help="Force legacy vi-paste flow (skip cookie fetch)")
    tl_p.add_argument("--browser", choices=["brave", "chrome", "safari", "firefox"],
                      default="brave", help="Browser to read 1001tracklists cookies from (default: brave)")

    # 1001tracklists-delete-session
    tl_del_p = sub.add_parser("1001tracklists-delete-session",
                               help="Delete a 1001tracklists session and its tracks")
    tl_del_p.add_argument("session_id", type=int)
    tl_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # text
    tx_p = sub.add_parser("text", help="Extract tracks from pasted text (no URL needed)")
    tx_p.add_argument("name", help="Session name / label for this tracklist")
    tx_p.add_argument("--url", default=None,
                      help="Associate a real URL with this session (e.g. the YouTube link)")
    tx_p.add_argument("--dry-run", action="store_true",
                      help="Run detection but skip all DB writes")

    # text-delete-session
    tx_del_p = sub.add_parser("text-delete-session", help="Delete a text session and its tracks")
    tx_del_p.add_argument("session_id", type=int)
    tx_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # mixcloud-delete-session
    mc_del_p = sub.add_parser("mixcloud-delete-session", help="Delete a Mixcloud session and its tracks")
    mc_del_p.add_argument("session_id", type=int)
    mc_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # youtube-delete-session
    yt_del_p = sub.add_parser("youtube-delete-session", help="Delete a YouTube session and its tracks")
    yt_del_p.add_argument("session_id", type=int)
    yt_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # soundcloud-delete-session
    sc_del_p = sub.add_parser("soundcloud-delete-session",
                              help="Delete a SoundCloud session and its tracks")
    sc_del_p.add_argument("session_id", type=int)
    sc_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # podbean-delete-session
    pb_del_p = sub.add_parser("podbean-delete-session", help="Delete a Podbean session and its tracks")
    pb_del_p.add_argument("session_id", type=int)
    pb_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    # gems
    gems_p = sub.add_parser("gems", help="Find hidden gem tracks on Spotify, SoundCloud, Bandcamp, or Beatport")
    gems_p.add_argument("--source", choices=["spotify", "soundcloud", "bandcamp", "beatport"],
                        default=None, help="Platform to search (interactive if omitted)")
    gems_p.add_argument("--genre", default=None, help="Genre to search (default: Tech House)")
    gems_p.add_argument("--count", "-n", type=int, default=None,
                        help="Number of tracks to return (1–20)")
    gems_p.add_argument("--date", choices=["1mo", "6mo", "1yr", "3yr"],
                        default=None, help="Max track age: 1mo / 6mo / 1yr / 3yr")
    gems_p.add_argument("--no-save", action="store_true", dest="no_save",
                        help="Don't persist results to the DB (testing only)")

    # fix-session
    fs_p = sub.add_parser(
        "fix-session",
        help="Correct a session's detected tracks using a confirmed tracklist from stdin",
    )
    fs_p.add_argument("session_id", type=int, help="Session ID to correct")
    fs_p.add_argument(
        "--apply", action="store_true",
        help="Actually delete wrong tracks (default: dry-run only)",
    )
    fs_p.add_argument(
        "--threshold", type=float, default=0.75, metavar="F",
        help="Fuzzy match threshold for keeping a detected track (default: 0.75)",
    )

    # spotify
    sp_p = sub.add_parser("spotify", help="Import tracks from a Spotify playlist into detected_tracks")
    sp_p.add_argument("url_or_name", help="Spotify playlist URL or playlist name to search for")

    # spotify-delete-session
    sp_del_p = sub.add_parser("spotify-delete-session",
                              help="Delete a Spotify playlist session and its tracks")
    sp_del_p.add_argument("session_id", type=int)
    sp_del_p.add_argument("--force", "-f", action="store_true", help="Skip confirmation prompt")

    return detect_p


def dispatch(args, detect_p: argparse.ArgumentParser) -> None:
    """Dispatch a parsed `dj detect ...` invocation."""
    import os
    migrate()

    if not args.detect_command:
        detect_p.print_help()
        return

    cmd = args.detect_command

    if cmd == "reddit":
        url = args.url
        if not args.dry_run:
            prior = find_session(url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                console.print(
                    f"\n[dim]This post was already scanned (session #{prior['id']}, "
                    f"{n_tracks} track(s) found).[/dim]\n"
                )
                if not _confirm("Scan again?", default=False):
                    sys.exit(0)

        # Extract subreddit from URL for display
        sr_m = __import__("re").search(r"/r/([^/?#]+)", url)
        subreddit = sr_m.group(1) if sr_m else "reddit"

        if args.dry_run:
            console.print("  [yellow]Dry run — no DB writes[/yellow]")

        console.print(
            f"\n[bold]Paste the post body into vi, then save and quit (:wq).[/bold]\n"
            f"[dim]URL: {url}[/dim]\n"
        )
        raw_text = reddit_open_editor(url)

        tracks = reddit_extract_from_text(raw_text)
        if not tracks:
            console.print("[yellow]No tracks found — nothing saved.[/yellow]")
            sys.exit(0)

        console.print(f"\n[bold]Found {len(tracks)} track(s) from r/{subreddit}:[/bold]\n")
        t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        t.add_column("#",      style="dim", width=4)
        t.add_column("Artist", min_width=22)
        t.add_column("Title",  min_width=28)
        for tr in tracks:
            t.add_row(str(tr["position"]), tr["artist"], tr["title"])
        console.print(t)

        # Derive a title from the URL slug
        slug = url.rstrip("/").split("/")[-1].replace("_", " ").title()
        if not args.dry_run:
            session_id = create_session(
                "reddit", url, slug,
                uploader=subreddit,
            )
            insert_tracks(tracks, source="reddit", session_id=session_id)
            end_session(session_id)
            console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")
        else:
            console.print("\n[yellow](dry run — nothing saved)[/yellow]")

    elif cmd == "reddit-delete-session":
        session_id = args.session_id
        rows = tracks_for_session(session_id)
        if not rows:
            console.print(f"[yellow]Session #{session_id} not found.[/yellow]")
            sys.exit(1)
        if not args.force:
            console.print(f"[yellow]Delete Reddit session #{session_id} ({len(rows)} track(s))?[/yellow]")
            if not _confirm("Confirm delete", default=False):
                sys.exit(0)
        n = delete_session(session_id)
        console.print(f"[green]Deleted session #{session_id}.[/green]")

    elif cmd == "topdjmixes":
        url = args.url
        if not args.dry_run:
            prior = find_session(url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                console.print(
                    f"\n[dim]This mix was already scanned (session #{prior['id']}, "
                    f"{n_tracks} track(s) found).[/dim]\n"
                )
                if not _confirm("Scan again?", default=False):
                    sys.exit(0)

        slug = url.rstrip("/").split("/")[-1] or "topdjmixes"
        dj_name = slug.replace("-", " ").replace("_", " ").title()

        if args.dry_run:
            console.print("  [yellow]Dry run — no DB writes[/yellow]")

        console.print(
            f"\n[bold]Paste the topdjmixes.com tracklist into vi, then save and quit (:wq).[/bold]\n"
            f"[dim]URL: {url}[/dim]\n"
        )
        raw_text = topdjmixes_open_editor(url)

        tracks = topdjmixes_extract_from_text(raw_text)
        if not tracks:
            console.print("[yellow]No tracks found — nothing saved.[/yellow]")
            sys.exit(0)

        console.print(f"\n[bold]Found {len(tracks)} track(s) from {dj_name}:[/bold]\n")
        t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        t.add_column("#",      style="dim", width=4)
        t.add_column("Artist", min_width=22)
        t.add_column("Title",  min_width=28)
        for tr in tracks:
            t.add_row(str(tr["position"]), tr["artist"], tr["title"])
        console.print(t)

        if not args.dry_run:
            session_id = create_session(
                "topdjmixes", url, dj_name,
                uploader=dj_name,
            )
            insert_tracks(tracks, source="topdjmixes", session_id=session_id)
            end_session(session_id)
            console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")
        else:
            console.print("\n[yellow](dry run — nothing saved)[/yellow]")

    elif cmd == "topdjmixes-delete-session":
        session_id = args.session_id
        rows = tracks_for_session(session_id)
        if not rows:
            console.print(f"[yellow]Session #{session_id} not found.[/yellow]")
            sys.exit(1)
        if not args.force:
            console.print(f"[yellow]Delete topdjmixes session #{session_id} ({len(rows)} track(s))?[/yellow]")
            if not _confirm("Confirm delete", default=False):
                sys.exit(0)
        n = delete_session(session_id)
        console.print(f"[green]Deleted session #{session_id}.[/green]")

    elif cmd == "1001tracklists":
        url = args.url
        if not args.dry_run:
            prior = find_session(url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                console.print(
                    f"[yellow]Already scanned:[/yellow] {prior['title'] or url} "
                    f"(session #{prior['id']}, {n_tracks} track(s))"
                )
                if not _confirm("Scan again?", default=False):
                    sys.exit(0)

        if args.dry_run:
            console.print("  [yellow]Dry run — no DB writes[/yellow]")

        if args.paste:
            console.print(
                f"\n[bold]Paste the 1001tracklists.com tracklist into vi, then save and quit (:wq).[/bold]\n"
                f"[dim]URL: {url}[/dim]\n"
            )
            raw_text = tracklists1001_open_editor(url)
        else:
            console.print(f"  Fetching tracklist via {args.browser} cookies…")
            try:
                raw_text = tracklists1001_fetch(url, args.browser)
            except Exception as exc:
                console.print(f"  [yellow]Cookie fetch failed ({exc}) — falling back to vi paste.[/yellow]")
                console.print(
                    f"\n[bold]Paste the 1001tracklists.com tracklist into vi, then save and quit (:wq).[/bold]\n"
                    f"[dim]URL: {url}[/dim]\n"
                )
                raw_text = tracklists1001_open_editor(url)

        tracks, skipped = tracklists1001_extract_from_text(raw_text)
        if not tracks:
            console.print("[yellow]No tracks found — nothing saved.[/yellow]")
            if skipped:
                console.print(f"\n[dim]Skipped {len(skipped)} unparseable line(s):[/dim]")
                for s in skipped:
                    console.print(f"  [dim]  {s}[/dim]")
            sys.exit(0)

        title = tracklists1001_extract_title(raw_text)
        dj_name = title or url.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()

        console.print(f"\n[bold]Found {len(tracks)} track(s) from \"{dj_name}\":[/bold]\n")
        t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        t.add_column("#",      style="dim", width=4)
        t.add_column("Artist", min_width=22)
        t.add_column("Title",  min_width=30)
        for tk in tracks:
            t.add_row(str(tk["position"]), tk["artist"], tk["title"])
        console.print(t)

        if skipped:
            console.print(f"\n[yellow]Skipped {len(skipped)} line(s) (no ' - ' separator or too long):[/yellow]")
            for s in skipped:
                console.print(f"  [dim]{s}[/dim]")

        if not args.dry_run:
            session_id = create_session("1001tracklists", url, dj_name, uploader=dj_name)
            for tk in tracks:
                tk_copy = dict(tk)
                if tk_copy.get("timestamp_s") is not None:
                    tk_copy["position"] = tk_copy["timestamp_s"]
                insert_track(tk_copy, source="1001tracklists", session_id=session_id)
            end_session(session_id)
            console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")
        else:
            console.print("\n[yellow](dry run — nothing saved)[/yellow]")

    elif cmd == "1001tracklists-delete-session":
        session_id = args.session_id
        rows = tracks_for_session(session_id)
        if not rows:
            console.print(f"[yellow]Session #{session_id} not found.[/yellow]")
            sys.exit(1)
        if not args.force:
            console.print(f"[yellow]Delete 1001tracklists session #{session_id} ({len(rows)} track(s))?[/yellow]")
            if not _confirm("Confirm delete", default=False):
                sys.exit(0)
        n = delete_session(session_id)
        console.print(f"[green]Deleted session #{session_id}.[/green]")

    elif cmd == "text":
        name = args.name
        slug = __import__("re").sub(r"[^a-z0-9_-]", "_", name.lower())[:60]
        ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%d_%H%M%S")
        fake_url = args.url if getattr(args, "url", None) else f"text://{slug}-{ts}"

        if args.dry_run:
            console.print("  [yellow]Dry run — no DB writes[/yellow]")

        console.print(
            f"\n[bold]Paste your tracklist into vi, then save and quit (:wq).[/bold]\n"
            f"[dim]Session: {name}[/dim]\n"
        )
        raw_text = text_open_editor(name)

        tracks, skipped = text_extract_from_text(raw_text)
        if not tracks:
            console.print("[yellow]No tracks found — nothing saved.[/yellow]")
            if skipped:
                console.print(f"\n[dim]Skipped {len(skipped)} unparseable line(s):[/dim]")
                for s in skipped:
                    console.print(f"  [dim]  {s}[/dim]")
            sys.exit(0)

        console.print(f"\n[bold]Found {len(tracks)} track(s) from \"{name}\":[/bold]\n")
        t = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
        t.add_column("#",      style="dim", width=4)
        t.add_column("Artist", min_width=22)
        t.add_column("Title",  min_width=30)
        for tk in tracks:
            t.add_row(str(tk["position"]), tk["artist"], tk["title"])
        console.print(t)

        if skipped:
            console.print(f"\n[yellow]Skipped {len(skipped)} line(s) (no ' - ' separator or too long):[/yellow]")
            for s in skipped:
                console.print(f"  [dim]{s}[/dim]")

        if not args.dry_run:
            session_id = create_session("text", fake_url, name, uploader=name)
            # Use timestamp_s as position when available so w/ overlays share
            # their parent track's timestamp. Falls back to sequential position.
            for tk in tracks:
                tk_copy = dict(tk)
                if tk_copy.get("timestamp_s") is not None:
                    tk_copy["position"] = tk_copy["timestamp_s"]
                insert_track(tk_copy, source="text", session_id=session_id)
            end_session(session_id)
            console.print(f"\n[dim]Saved to DB (session #{session_id})[/dim]")
        else:
            console.print("\n[yellow](dry run — nothing saved)[/yellow]")

    elif cmd == "text-delete-session":
        session_id = args.session_id
        rows = tracks_for_session(session_id)
        if not rows:
            console.print(f"[yellow]Session #{session_id} not found.[/yellow]")
            sys.exit(1)
        if not args.force:
            console.print(f"[yellow]Delete text session #{session_id} ({len(rows)} track(s))?[/yellow]")
            if not _confirm("Confirm delete", default=False):
                sys.exit(0)
        n = delete_session(session_id)
        console.print(f"[green]Deleted session #{session_id}.[/green]")

    elif cmd == "instagram":
        saved_u, saved_p = _load_saved_credentials(service="instagram")
        username = args.username or os.environ.get("IG_USERNAME") or saved_u
        password = args.password or os.environ.get("IG_PASSWORD") or saved_p
        if not username:
            username = input("Instagram username: ")
        if not password:
            password = getpass.getpass("Instagram password: ")
        asyncio.run(_run(args.url, username, password, args.output, args.json_output,
                         dry_run=args.dry_run))
        # Auto-save so the next run logs in without prompting (login just succeeded).
        if username and password and (username, password) != (saved_u, saved_p):
            _save_credentials(username, password, service="instagram")

    elif cmd == "radio-garden":
        if args.capture >= args.interval:
            console.print(f"[red]--capture ({args.capture}s) must be shorter than --interval ({args.interval}s)[/red]")
            sys.exit(1)
        with caffeinate():
            asyncio.run(_run_radio(args.url, interval=args.interval, capture_s=args.capture,
                                   duration_min=args.duration, cooldown=args.cooldown,
                                   dry_run=args.dry_run))

    elif cmd == "mixcloud":
        if args.capture >= args.interval:
            console.print(f"[red]--capture ({args.capture}s) must be shorter than --interval ({args.interval}s)[/red]")
            sys.exit(1)
        saved_u, saved_p = _load_saved_credentials(service="mixcloud")
        username = args.username or os.environ.get("MC_USERNAME") or saved_u
        password = args.password or os.environ.get("MC_PASSWORD") or saved_p
        # Auto-save freshly provided creds so the next run reuses them (Mixcloud
        # auth is optional; yt-dlp validates them at download time).
        if username and password and (username, password) != (saved_u, saved_p):
            _save_credentials(username, password, service="mixcloud")

        resume_session_id: int | None = None
        resume_from: int = 0
        if not args.dry_run:
            prior = find_session(args.url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                last_pos = prior["last_scanned_position"]
                dur = prior["duration_seconds"] or 0
                if last_pos is None and n_tracks:
                    last_pos = infer_last_position(prior["id"])
                is_partial = last_pos is not None and (not dur or last_pos < dur - args.interval)
                if is_partial:
                    note = " (position inferred from tracks)" if prior["last_scanned_position"] is None else ""
                    console.print(
                        f"\n[yellow]Found an incomplete session (#{prior['id']}) for this mix.[/yellow]\n"
                        f"  Last scanned: [bold]{_fmt_time(last_pos)}[/bold]{note}  ·  {n_tracks} track(s) found so far\n"
                    )
                    if _confirm("Resume from where it left off?", default=True):
                        resume_session_id = prior["id"]
                        resume_from = last_pos
                        if prior["last_scanned_position"] is None:
                            update_session_progress(prior["id"], last_pos)
                    else:
                        console.print("")
                else:
                    scanned_on = prior["started_at"][:10]
                    console.print(
                        f"\n[dim]This mix was already scanned on {scanned_on} "
                        f"({n_tracks} track(s) found, session #{prior['id']}).[/dim]\n"
                    )
                    if not _confirm("Scan again from the beginning?", default=False):
                        sys.exit(0)
                    console.print("")

        asyncio.run(_run_mixcloud(
            args.url, username, password, args.interval, args.capture,
            args.output, args.json_output,
            resume_session_id=resume_session_id, resume_from=resume_from,
            dry_run=args.dry_run,
        ))

    elif cmd == "youtube":
        if args.capture >= args.interval:
            console.print(f"[red]--capture ({args.capture}s) must be shorter than --interval ({args.interval}s)[/red]")
            sys.exit(1)

        resume_session_id = None
        resume_from = 0
        if not args.dry_run:
            prior = find_session(args.url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                last_pos = prior["last_scanned_position"]
                dur = prior["duration_seconds"] or 0
                if last_pos is None and n_tracks:
                    last_pos = infer_last_position(prior["id"])
                is_partial = last_pos is not None and (not dur or last_pos < dur - args.interval)
                if is_partial:
                    note = " (position inferred from tracks)" if prior["last_scanned_position"] is None else ""
                    console.print(
                        f"\n[yellow]Found an incomplete session (#{prior['id']}) for this video.[/yellow]\n"
                        f"  Last scanned: [bold]{_fmt_time(last_pos)}[/bold]{note}  ·  {n_tracks} track(s) found so far\n"
                    )
                    if _confirm("Resume from where it left off?", default=True):
                        resume_session_id = prior["id"]
                        resume_from = last_pos
                        if prior["last_scanned_position"] is None:
                            update_session_progress(prior["id"], last_pos)
                    else:
                        console.print("")
                else:
                    scanned_on = prior["started_at"][:10]
                    console.print(
                        f"\n[dim]This video was already scanned on {scanned_on} "
                        f"({n_tracks} track(s) found, session #{prior['id']}).[/dim]\n"
                    )
                    if not _confirm("Scan again from the beginning?", default=False):
                        sys.exit(0)
                    console.print("")

        asyncio.run(_run_youtube(args.url, args.interval, args.capture, args.output, args.json_output,
                                 resume_session_id=resume_session_id, resume_from=resume_from,
                                 dry_run=args.dry_run))

    elif cmd == "soundcloud":
        from connections import soundcloud as sc_api
        from .soundcloud import (
            clean_url as sc_clean_url,
            is_personalized_url as sc_is_personalized_url,
            is_set_url as sc_is_set_url,
            resolve_mix as sc_resolve_mix,
        )
        url = sc_clean_url(args.url)

        # Personalized /discover/ URLs are handled inside _run_soundcloud_set
        # → list_set_tracks → connections/soundcloud_browser.py (Playwright).
        # First-run pops a visible browser so the user can log in if needed.

        # Set → enumerate child tracks (no audio scan, no Shazam)
        if sc_is_set_url(url) or sc_is_personalized_url(url):
            _run_soundcloud_set(url, dry_run=args.dry_run)
            return

        # Single track → peek at duration to decide between single-song
        # metadata-only save vs Shazam-scan of a long DJ mix
        with console.status("Resolving track info…"):
            try:
                track_title, uploader, duration = sc_resolve_mix(url)
            except RuntimeError as exc:
                console.print(f"[red]Error:[/red] {exc}")
                sys.exit(1)

        if duration and duration <= SOUNDCLOUD_SONG_DURATION_S:
            _save_soundcloud_song(url, track_title, uploader, duration, dry_run=args.dry_run)
            return

        # Long single track → DJ mix → Shazam-scan the audio
        if args.capture >= args.interval:
            console.print(f"[red]--capture ({args.capture}s) must be shorter than --interval ({args.interval}s)[/red]")
            sys.exit(1)

        resume_session_id = None
        resume_from = 0
        if not args.dry_run:
            prior = find_session(url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                last_pos = prior["last_scanned_position"]
                dur = prior["duration_seconds"] or 0
                if last_pos is None and n_tracks:
                    last_pos = infer_last_position(prior["id"])
                is_partial = last_pos is not None and (not dur or last_pos < dur - args.interval)
                if is_partial:
                    note = " (position inferred from tracks)" if prior["last_scanned_position"] is None else ""
                    console.print(
                        f"\n[yellow]Found an incomplete session (#{prior['id']}) for this mix.[/yellow]\n"
                        f"  Last scanned: [bold]{_fmt_time(last_pos)}[/bold]{note}  ·  {n_tracks} track(s) found so far\n"
                    )
                    if _confirm("Resume from where it left off?", default=True):
                        resume_session_id = prior["id"]
                        resume_from = last_pos
                        if prior["last_scanned_position"] is None:
                            update_session_progress(prior["id"], last_pos)
                    else:
                        console.print("")
                else:
                    scanned_on = prior["started_at"][:10]
                    console.print(
                        f"\n[dim]This mix was already scanned on {scanned_on} "
                        f"({n_tracks} track(s) found, session #{prior['id']}).[/dim]\n"
                    )
                    if not _confirm("Scan again from the beginning?", default=False):
                        sys.exit(0)
                    console.print("")

        asyncio.run(_run_soundcloud(url, args.interval, args.capture, args.output, args.json_output,
                                    resume_session_id=resume_session_id, resume_from=resume_from,
                                    dry_run=args.dry_run))

    elif cmd == "podbean":
        if args.capture >= args.interval:
            console.print(f"[red]--capture ({args.capture}s) must be shorter than --interval ({args.interval}s)[/red]")
            sys.exit(1)

        resume_session_id = None
        resume_from = 0
        if not args.dry_run:
            prior = find_session(args.url)
            if prior:
                n_tracks = len(tracks_for_session(prior["id"]))
                last_pos = prior["last_scanned_position"]
                dur = prior["duration_seconds"] or 0
                if last_pos is None and n_tracks:
                    last_pos = infer_last_position(prior["id"])
                is_partial = last_pos is not None and (not dur or last_pos < dur - args.interval)
                if is_partial:
                    note = " (position inferred from tracks)" if prior["last_scanned_position"] is None else ""
                    console.print(
                        f"\n[yellow]Found an incomplete session (#{prior['id']}) for this episode.[/yellow]\n"
                        f"  Last scanned: [bold]{_fmt_time(last_pos)}[/bold]{note}  ·  {n_tracks} track(s) found so far\n"
                    )
                    if _confirm("Resume from where it left off?", default=True):
                        resume_session_id = prior["id"]
                        resume_from = last_pos
                        if prior["last_scanned_position"] is None:
                            update_session_progress(prior["id"], last_pos)
                    else:
                        console.print("")
                else:
                    scanned_on = prior["started_at"][:10]
                    console.print(
                        f"\n[dim]This episode was already scanned on {scanned_on} "
                        f"({n_tracks} track(s) found, session #{prior['id']}).[/dim]\n"
                    )
                    if not _confirm("Scan again from the beginning?", default=False):
                        sys.exit(0)
                    console.print("")

        asyncio.run(_run_podbean(args.url, args.interval, args.capture, args.output, args.json_output,
                                 resume_session_id=resume_session_id, resume_from=resume_from,
                                 dry_run=args.dry_run))

    elif cmd == "mixcloud-delete-session":
        rows = list_sessions("mixcloud", 100)
        session = next((r for r in rows if r["id"] == args.session_id), None)
        if not session:
            console.print(f"[red]Session #{args.session_id} not found.[/red]")
            sys.exit(1)
        n_tracks = len(tracks_for_session(args.session_id))
        console.print(
            f"Session #{args.session_id}: [bold]{session['title']}[/bold]  "
            f"({n_tracks} track(s), scanned {session['started_at'][:10]})"
        )
        if not args.force and not _confirm("Delete this session and its tracks?", default=False):
            sys.exit(0)
        delete_session(args.session_id)
        console.print(f"[green]✓[/green] Deleted session #{args.session_id} and {n_tracks} track(s).")

    elif cmd == "youtube-delete-session":
        rows = list_sessions("youtube", 100)
        session = next((r for r in rows if r["id"] == args.session_id), None)
        if not session:
            console.print(f"[red]Session #{args.session_id} not found.[/red]")
            sys.exit(1)
        n_tracks = len(tracks_for_session(args.session_id))
        console.print(
            f"Session #{args.session_id}: [bold]{session['title']}[/bold]  "
            f"({n_tracks} track(s), scanned {session['started_at'][:10]})"
        )
        if not args.force and not _confirm("Delete this session and its tracks?", default=False):
            sys.exit(0)
        delete_session(args.session_id)
        console.print(f"[green]✓[/green] Deleted session #{args.session_id} and {n_tracks} track(s).")

    elif cmd == "soundcloud-delete-session":
        rows = list_sessions("soundcloud", 100)
        session = next((r for r in rows if r["id"] == args.session_id), None)
        if not session:
            console.print(f"[red]Session #{args.session_id} not found.[/red]")
            sys.exit(1)
        n_tracks = len(tracks_for_session(args.session_id))
        console.print(
            f"Session #{args.session_id}: [bold]{session['title']}[/bold]  "
            f"({n_tracks} track(s), scanned {session['started_at'][:10]})"
        )
        if not args.force and not _confirm("Delete this session and its tracks?", default=False):
            sys.exit(0)
        delete_session(args.session_id)
        console.print(f"[green]✓[/green] Deleted session #{args.session_id} and {n_tracks} track(s).")

    elif cmd == "podbean-delete-session":
        rows = list_sessions("podbean", 100)
        session = next((r for r in rows if r["id"] == args.session_id), None)
        if not session:
            console.print(f"[red]Session #{args.session_id} not found.[/red]")
            sys.exit(1)
        n_tracks = len(tracks_for_session(args.session_id))
        console.print(
            f"Session #{args.session_id}: [bold]{session['title']}[/bold]  "
            f"({n_tracks} track(s), scanned {session['started_at'][:10]})"
        )
        if not args.force and not _confirm("Delete this session and its tracks?", default=False):
            sys.exit(0)
        delete_session(args.session_id)
        console.print(f"[green]✓[/green] Deleted session #{args.session_id} and {n_tracks} track(s).")

    elif cmd == "gems":
        from detect.gems import DATE_KEYS, DATE_DAYS, run_gems
        max_age_days = None
        if args.date:
            max_age_days = DATE_DAYS[DATE_KEYS.index(args.date)]
        run_gems(
            source=args.source,
            genre=args.genre,
            count=args.count,
            max_age_days=max_age_days,
            no_save=args.no_save,
        )

    elif cmd == "spotify":
        from detect.spotify import run_spotify_playlist
        run_spotify_playlist(args.url_or_name)

    elif cmd == "spotify-delete-session":
        rows = list_sessions("spotify", 100)
        session = next((r for r in rows if r["id"] == args.session_id), None)
        if not session:
            console.print(f"[red]Session #{args.session_id} not found.[/red]")
            sys.exit(1)
        n_tracks = len(tracks_for_session(args.session_id))
        console.print(
            f"Session #{args.session_id}: [bold]{session['title']}[/bold]  "
            f"({n_tracks} track(s), imported {session['started_at'][:10]})"
        )
        if not args.force and not _confirm("Delete this session and its tracks?", default=False):
            sys.exit(0)
        delete_session(args.session_id)
        console.print(f"[green]✓[/green] Deleted session #{args.session_id} and {n_tracks} track(s).")

    elif cmd == "fix-session":
        _cmd_fix_session(args)
