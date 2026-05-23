"""Auto-fetch 1001tracklists.com tracklists via browser cookies.

Replicates the content.js export_data.php call without requiring paste/vi.
"""

from __future__ import annotations

import json
import re

import httpx

from connections.cookies import load_cookie_jar


def extract_idtl(url: str) -> str:
    m = re.search(r"/tracklist/([^/]+)", url)
    if not m:
        raise ValueError(f"Cannot extract tracklist ID from URL: {url}")
    return m.group(1)


def _strip_ellipsis(s: str) -> str:
    return re.sub(r"^(?:\.{3}|…)\s*", "", s).rstrip(".…").strip()


def _json_to_paste_text(data: list | dict) -> str:
    """Convert the API JSON array to [HH:MM:SS] Artist - Title plain text."""
    if isinstance(data, dict):
        raw = data.get("tracks") or data.get("tracklist") or list(data.values())
    else:
        raw = data

    lines: list[str] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        artist = _strip_ellipsis(
            t.get("artistName") or t.get("artist") or t.get("trackArtist") or t.get("artist_name") or ""
        )
        track = _strip_ellipsis(
            t.get("trackName") or t.get("track") or t.get("trackTitle") or t.get("track_name") or t.get("name") or t.get("title") or ""
        )
        time_ = t.get("startTime") or t.get("time") or t.get("timestamp") or t.get("start_time") or ""
        w = bool(t.get("isWithTrack") or t.get("type") == "with" or t.get("w") or t.get("is_with"))

        # Heuristic: split "Artist - Title" when artist is missing
        if not artist and " - " in track:
            idx = track.index(" - ")
            artist = track[:idx].strip()
            track = track[idx + 3:].strip()

        if not artist and not track:
            continue

        if w:
            lines.append(f"w/ {artist} - {track}" if artist else f"w/ {track}")
        else:
            timestamp = f"[{time_}] " if time_ else ""
            lines.append(f"{timestamp}{artist} - {track}" if artist else f"{timestamp}{track}")

    return "\n".join(lines)


def fetch_tracklist_text(url: str, browser: str = "brave") -> str:
    """POST to 1001tracklists export_data.php using browser cookies; return plain text."""
    idtl = extract_idtl(url)
    jar = load_cookie_jar("1001tracklists.com", browser)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": url,
    }

    with httpx.Client(cookies=jar, headers=headers, follow_redirects=True, timeout=20) as client:
        resp = client.post(
            "https://www.1001tracklists.com/ajax/export_data.php",
            data={"object": "tracklist", "idTL": idtl},
        )
        resp.raise_for_status()
        body = resp.text.strip()

    if not body:
        raise RuntimeError("1001tracklists returned an empty response — are you logged in?")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body  # already plain text in [MM:SS] format

    if isinstance(parsed, list):
        return _json_to_paste_text(parsed)
    if isinstance(parsed, dict):
        if parsed.get("success") is False:
            raise RuntimeError(parsed.get("message") or "API returned success:false")
        data = parsed.get("data")
        if isinstance(data, str):
            return data
        if data is not None:
            return _json_to_paste_text(data)
    return body
