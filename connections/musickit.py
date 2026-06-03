"""Wrapper around the Swift musickit_bridge — auto-compile, run, and stream tracks."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

_BRIDGE_SRC = Path(__file__).resolve().parent / "bridge" / "musickit_bridge.swift"
from paths import MUSICKIT_CACHE_DIR as _CACHE_DIR


def _bridge_binary() -> Path:
    """Compile musickit_bridge.swift if needed. Cache by source hash."""
    src = _BRIDGE_SRC
    src_hash = hashlib.md5(src.read_bytes()).hexdigest()[:8]
    binary = _CACHE_DIR / f"musickit_bridge_{src_hash}"
    if not binary.exists():
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for old in _CACHE_DIR.glob("musickit_bridge_*"):
            old.unlink(missing_ok=True)
        result = subprocess.run(
            ["swiftc", str(src), "-o", str(binary)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Swift compile failed:\n{result.stderr}")
    return binary


def _stream_bridge(args: list[str]):
    """Run the MusicKit bridge with given args and yield track dicts from NDJSON stdout."""
    binary = _bridge_binary()
    proc = subprocess.Popen(
        [str(binary)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    finally:
        proc.stdout.close()

    exit_code = proc.wait()
    if exit_code != 0:
        stderr = proc.stderr.read()
        raise RuntimeError(
            f"MusicKit bridge exited with code {exit_code}. "
            f"Sync may be incomplete.\n{stderr.strip()}"
        )


def stream_library_tracks():
    """Yield track dicts for songs with libraryAddedDate set (Music app 'Songs' tab)."""
    yield from _stream_bridge(["--library-songs"])


def stream_favorite_tracks():
    """Yield track dicts for songs in the 'Favourite Songs' playlist."""
    yield from _stream_bridge(["--favorites"])


def stream_all_playlists():
    """Yield one dict per playlist ENTRY, in order, for faithful capture.

    Each dict: playlist_name, native_playlist_id, position, native_track_id,
    library_id, url, name, artist, album. Duplicates and ordering are preserved.
    """
    yield from _stream_bridge(["--all-playlists"])


def _osa_escape(s: str) -> str:
    """Escape a string for an AppleScript double-quoted literal."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def build_create_playlist_applescript(name: str, tracks: list[dict]) -> str:
    """Build the AppleScript that creates a Music.app playlist and fills it.

    MusicKit can't write the library on macOS (`createPlaylist` AND `add` are both
    unavailable, and AppleScript can't reference a track by Apple Music catalog id —
    it isn't exposed), so the only supported path is scripting Music.app. Per track,
    in order of robustness:
      1. `persistent ID` — the library track's STABLE id (captured at sync time);
         an exact, collision-proof match that survives metadata edits and dupes.
      2. name + artist (+ captured `album` as a tiebreaker when several collide) —
         fallback for rows with no captured persistent id (older captures, other
         sources) or whose persistent id no longer resolves.
    A track no longer in the library can't be restored at all (no API re-adds a
    catalog track on macOS); it's skipped, surfaced via added-vs-requested. Pure so
    it can be unit-tested.
    """
    lines = [
        'tell application "Music"',
        f'set newPl to make new user playlist with properties {{name:"{_osa_escape(name)}"}}',
    ]
    for t in tracks:
        title = _osa_escape(t.get("title") or "")
        artist = _osa_escape(t.get("artist") or "")
        album = _osa_escape(t.get("album") or "")
        pid = _osa_escape(t.get("native_persistent_id") or "")
        lines.append("set chosen to missing value")
        if pid:
            # Exact match by stable persistent id; `try` swallows "not found".
            lines.append("try")
            lines.append(f'set chosen to (first track of library playlist 1 whose persistent ID is "{pid}")')
            lines.append("end try")
        lines.append("if chosen is missing value then")
        lines.append(
            f'set ms to (every track of library playlist 1 whose name is "{title}" '
            f'and artist is "{artist}")'
        )
        lines.append("if ms is not {} then")
        lines.append("set chosen to item 1 of ms")
        if album:
            # Prefer the exact-album match when there's more than one candidate;
            # otherwise keep item 1 (never drop a name+artist match).
            lines.append("if (count of ms) > 1 then")
            lines.append("repeat with c in ms")
            lines.append(f'if (album of c) is "{album}" then')
            lines.append("set chosen to c")
            lines.append("exit repeat")
            lines.append("end if")
            lines.append("end repeat")
            lines.append("end if")
        lines.append("end if")
        lines.append("end if")
        lines.append("if chosen is not missing value then duplicate chosen to newPl")
    lines.append("return (count of tracks of newPl) as string")
    lines.append("end tell")
    return "\n".join(lines)


def read_playlist_persistent_ids(name: str) -> list[tuple[str, str]] | None:
    """Return [(persistent_id, track_name), …] in order for the playlist named `name`.

    Used at capture time to attach a stable per-track id for exact restore. Returns
    None when the lookup is ambiguous or unavailable — a duplicate playlist name
    (can't tell which one), a missing playlist, or any AppleScript error — so the
    caller falls back to name+artist matching rather than attach the wrong ids.
    Persistent id + name are tab-joined per line; names can't contain tab/newline.
    """
    safe = _osa_escape(name)
    script = "\n".join([
        'tell application "Music"',
        f'set matches to (every playlist whose name is "{safe}")',
        'if (count of matches) is not 1 then return "AMBIGUOUS"',
        "set pl to item 1 of matches",
        "set pids to (persistent ID of every track of pl)",
        "set nms to (name of every track of pl)",
        'set out to ""',
        "repeat with i from 1 to (count of pids)",
        '   set out to out & (item i of pids) & tab & (item i of nms) & linefeed',
        "end repeat",
        "return out",
        "end tell",
    ])
    try:
        out = _run_osascript(script, timeout=120)
    except RuntimeError:
        return None
    if out.strip() == "AMBIGUOUS":
        return None
    pairs: list[tuple[str, str]] = []
    for line in out.split("\n"):
        if not line:
            continue
        pid, _, track_name = line.partition("\t")
        pairs.append((pid, track_name))
    return pairs


def _run_osascript(script: str, timeout: int = 600) -> str:
    """Run an AppleScript via osascript stdin; return stdout. Raises on non-zero exit."""
    proc = subprocess.run(
        ["osascript", "-"],
        input=script, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript (Music.app) failed: {proc.stderr.strip()}")
    return (proc.stdout or "").strip()


def _library_track_count() -> int:
    out = _run_osascript('tell application "Music" to return count of tracks in library playlist 1', timeout=120)
    try:
        return int(out or "0")
    except ValueError:
        return 0


def clear_apple_library(batch_size: int = 100) -> int:
    """Remove every track from the Apple Music library. Returns the count removed.

    Deletes in batches (each its own AppleScript call) so a large library doesn't
    blow the osascript timeout — same approach as helpers/clear_apple_music.py.
    Library removal cascades: a deleted track also leaves any playlists it was in.
    DESTRUCTIVE and not undoable from here — callers must back up + confirm first.
    """
    deleted = 0
    while True:
        remaining = _library_track_count()
        if remaining == 0:
            break
        take = min(batch_size, remaining)
        _run_osascript(
            'tell application "Music"\n'
            f"set trackList to (tracks 1 through {take} of library playlist 1)\n"
            "repeat with t in trackList\n"
            "delete t\n"
            "end repeat\n"
            "end tell",
            timeout=300,
        )
        deleted += take
    return deleted


def build_delete_playlist_applescript(name: str) -> str:
    """Build the AppleScript that deletes playlist(s) named `name` from Music.app.

    MusicKit can't delete library playlists on macOS (same limitation as create),
    so the supported path is scripting Music.app. Deletes EVERY matching playlist
    (Music.app allows duplicate names) and returns how many were removed. The
    underlying library tracks are untouched — only the playlist (a container) is
    removed. Pure so it can be unit-tested.

    Matches `every playlist … whose special kind is none` rather than `every user
    playlist`: capture also pulls **subscription playlists** (curated Apple Music
    playlists the user follows, e.g. "<artist> Essentials"), which are NOT
    `user playlist`s, so a `user playlist` filter silently leaves them behind
    ("not found in Apple Music"). `special kind is none` admits both user and
    subscription playlists while excluding the system playlists — Library, Music,
    Purchased, Downloaded, Genius — whose `special kind` is non-`none`.
    """
    # NB: `matched` is a reserved term in Music.app's AppleScript dictionary (the
    # smart-playlist match rule), so `set matched to …` writes a read-only constant
    # and fails with -10003 "Access not allowed". Use a non-reserved variable name.
    return "\n".join([
        'tell application "Music"',
        f'set theMatches to (every playlist whose name is "{_osa_escape(name)}" and special kind is none)',
        "set n to (count of theMatches)",
        "repeat with p in theMatches",
        "delete p",
        "end repeat",
        "return n as string",
        "end tell",
    ])


def delete_apple_playlist(name: str) -> dict:
    """Delete user playlist(s) named `name` from Music.app. Returns {deleted, name}.

    `deleted` is the number of playlists removed (0 if none matched). The library
    tracks themselves are never touched — deleting a playlist only removes the
    container. Raises RuntimeError on a non-zero osascript exit.
    """
    out = _run_osascript(build_delete_playlist_applescript(name))
    try:
        deleted = int(out or "0")
    except ValueError:
        deleted = 0
    return {"deleted": deleted, "name": name}


def read_live_playlist_names() -> set[str]:
    """Return the names of every deletable playlist currently in Music.app.

    "Deletable" mirrors the delete selector's universe (`special kind is none`):
    user + subscription playlists, excluding the system playlists (Library, Music,
    Purchased, …). Used to filter the delete-target list down to what actually still
    exists — the dj.db backup is permanent and never forgets a playlist, so a
    playlist deleted in a prior run would otherwise resurface forever as
    "not found in Apple Music". Returns an empty set on any AppleScript error so the
    caller falls back to attempting every captured target (no silent data loss).
    """
    script = "\n".join([
        'tell application "Music"',
        "set nms to (name of (every playlist whose special kind is none))",
        'set out to ""',
        "repeat with nm in nms",
        "   set out to out & nm & linefeed",
        "end repeat",
        "return out",
        "end tell",
    ])
    try:
        out = _run_osascript(script, timeout=120)
    except RuntimeError:
        return set()
    return {line for line in out.split("\n") if line}


def create_apple_playlist(name: str, tracks: list[dict]) -> dict:
    """Create a Music.app playlist `name` from `tracks` ({artist, title, album} each).

    Matches each track against the local library by name + artist via AppleScript
    (the macOS-supported path), disambiguating duplicates by `album` when known.
    Returns {created, name, requested, added}; `added` < `requested` means some
    tracks were no longer in the library (unrestorable on macOS). Raises
    RuntimeError on a non-zero osascript exit.
    """
    script = build_create_playlist_applescript(name, tracks)
    proc = subprocess.run(
        ["osascript", "-"],
        input=script, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"AppleScript (Music.app) failed: {proc.stderr.strip()}")
    try:
        added = int((proc.stdout or "0").strip() or "0")
    except ValueError:
        added = 0
    return {"created": True, "name": name, "requested": len(tracks), "added": added}


# ── Restore helpers (bulk `playlist push --library/--favorite-only/--readd-missing`) ──


def library_track_key(title: str | None, artist: str | None) -> str:
    """Stable name+artist key for matching a track against the library by content.

    Used for `--readd-missing` idempotency: a re-added catalog track gets a fresh
    persistent id, so we can't match it by the captured one — name+artist is what
    survives the round-trip.
    """
    return f"{(title or '').strip().casefold()}\x00{(artist or '').strip().casefold()}"


def read_library_track_keys() -> set[str]:
    """Return the set of name+artist keys for every track currently in the library.

    One AppleScript call (two `… of every track` reads, zipped in-script) so it's
    fast even for thousands of tracks. Used to skip tracks already present.
    """
    script = "\n".join([
        'tell application "Music"',
        "set nms to (name of every track of library playlist 1)",
        "set ars to (artist of every track of library playlist 1)",
        'set out to ""',
        "repeat with i from 1 to (count of nms)",
        "   set out to out & (item i of nms) & tab & (item i of ars) & linefeed",
        "end repeat",
        "return out",
        "end tell",
    ])
    out = _run_osascript(script, timeout=300)
    keys: set[str] = set()
    for line in out.split("\n"):
        if not line:
            continue
        name, _, artist = line.partition("\t")
        keys.add(library_track_key(name, artist))
    return keys


def readd_track_by_catalog_id(catalog_id: str) -> None:
    """Best-effort: ask Music.app to add a catalog track back to the library.

    macOS has NO supported API to add a catalog track to the library (MusicKit
    `add` is `@available(macOS, unavailable)`), so this falls back to the `itmss://`
    store-URL trick `restore_apple_music.py` uses. EXPERIMENTAL and unreliable:
    region-locked / removed tracks won't add. Fire-and-forget — the caller paces the
    calls and re-reads `read_library_track_keys()` afterwards to see what landed.
    """
    cid = (catalog_id or "").strip()
    if not cid:
        return
    _run_osascript(
        'tell application "Music" to open location '
        f'"itmss://itunes.apple.com/song?id={cid}"',
        timeout=30,
    )


def build_mark_loved_applescript(tracks: list[dict]) -> str:
    """AppleScript that re-marks each track as loved (persistent id → name+artist). Pure."""
    lines = ['tell application "Music"', "set n to 0"]
    for t in tracks:
        title = _osa_escape(t.get("title") or "")
        artist = _osa_escape(t.get("artist") or "")
        pid = _osa_escape(t.get("native_persistent_id") or "")
        lines.append("set chosen to missing value")
        if pid:
            lines.append("try")
            lines.append(f'set chosen to (first track of library playlist 1 whose persistent ID is "{pid}")')
            lines.append("end try")
        lines.append("if chosen is missing value then")
        lines.append(f'set ms to (every track of library playlist 1 whose name is "{title}" '
                     f'and artist is "{artist}")')
        lines.append("if ms is not {} then set chosen to item 1 of ms")
        lines.append("end if")
        lines.append("if chosen is not missing value then")
        lines.append("set loved of chosen to true")
        lines.append("set n to n + 1")
        lines.append("end if")
    lines.append("return n as string")
    lines.append("end tell")
    return "\n".join(lines)


def mark_loved(tracks: list[dict]) -> int:
    """Re-mark captured favorite tracks as loved in the library. Returns the count set."""
    if not tracks:
        return 0
    out = _run_osascript(build_mark_loved_applescript(tracks))
    try:
        return int(out or "0")
    except ValueError:
        return 0
