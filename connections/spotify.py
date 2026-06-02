"""Spotify Web API client with user-scoped OAuth (Authorization Code flow).

`detect/spotify.py` uses *client-credentials* auth — fine for reading PUBLIC
playlists by URL, but it cannot see a user's own/private playlists or library, and
cannot write. `dj sync spotify` (capture all your playlists) and
`dj sync spotify playlist push` (create a playlist) both need user scope, so this
module runs the Authorization Code flow once, stores the refresh token in dj.db
(`auth_cache`, via `sync.db`), and refreshes the short-lived access token on demand.

Setup (one-time): create an app at developer.spotify.com, add redirect URI
`http://127.0.0.1:8888/callback`, then set SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
in .env. The first `dj sync spotify` opens a browser to authorize.
"""
from __future__ import annotations

import base64
import os
import time
import urllib.parse
import webbrowser
from typing import Optional

import httpx

_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"

REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
SCOPES = (
    "playlist-read-private playlist-read-collaborative user-library-read "
    "playlist-modify-public playlist-modify-private"
)

_AUTH_SERVICE = "spotify"  # auth_cache key for the refresh token


class SpotifyAuthError(Exception):
    """Raised when Spotify credentials are missing or authorization fails."""


def _credentials() -> tuple[str, str]:
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise SpotifyAuthError(
            "Spotify credentials missing. Create an app at developer.spotify.com "
            f"(redirect URI {REDIRECT_URI}), then set SPOTIFY_CLIENT_ID and "
            "SPOTIFY_CLIENT_SECRET in .env."
        )
    return cid, secret


def _basic_auth_header(cid: str, secret: str) -> dict:
    raw = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _redirect_port() -> int:
    return urllib.parse.urlparse(REDIRECT_URI).port or 8888


def _authorize_interactive(cid: str, secret: str) -> tuple[str, str]:
    """Run the loopback OAuth dance. Returns (access_token, refresh_token).

    Opens the system browser to Spotify's consent page, then catches the
    redirect on a one-shot local HTTP server to read the auth `code`.
    """
    import http.server
    import socketserver

    state = base64.urlsafe_b64encode(os.urandom(12)).decode()
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    }
    auth_url = f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"

    captured: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.urlparse(self.path).query
            q = urllib.parse.parse_qs(qs)
            captured["code"] = (q.get("code") or [""])[0]
            captured["state"] = (q.get("state") or [""])[0]
            captured["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Spotify authorized. You can close this tab.</body></html>")

        def log_message(self, *a):  # silence the default stderr logging
            pass

    print(f"Opening browser to authorize Spotify…\nIf it doesn't open, visit:\n{auth_url}")
    webbrowser.open(auth_url)

    with socketserver.TCPServer(("127.0.0.1", _redirect_port()), _Handler) as httpd:
        httpd.handle_request()  # blocks until the redirect hits

    if captured.get("error"):
        raise SpotifyAuthError(f"Spotify authorization denied: {captured['error']}")
    if not captured.get("code") or captured.get("state") != state:
        raise SpotifyAuthError("Spotify authorization failed (missing code or state mismatch).")

    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": captured["code"],
            "redirect_uri": REDIRECT_URI,
        },
        headers=_basic_auth_header(cid, secret),
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data["refresh_token"]


def _refresh_access(cid: str, secret: str, refresh_token: str) -> tuple[str, Optional[str]]:
    """Exchange a refresh token for a fresh access token. Returns (access, maybe-new-refresh)."""
    resp = httpx.post(
        _TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers=_basic_auth_header(cid, secret),
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], data.get("refresh_token")


def get_access_token() -> str:
    """Resolve a usable access token: refresh if we have a stored token, else authorize."""
    from sync import db as sync_db

    cid, secret = _credentials()
    refresh = sync_db.get_auth(_AUTH_SERVICE)
    if refresh:
        try:
            access, rotated = _refresh_access(cid, secret, refresh)
            if rotated and rotated != refresh:
                sync_db.set_auth(_AUTH_SERVICE, rotated)
            return access
        except Exception:
            pass  # fall through to a fresh interactive authorize

    access, refresh = _authorize_interactive(cid, secret)
    sync_db.set_auth(_AUTH_SERVICE, refresh)
    return access


def make_client() -> "Spotify":
    return Spotify(get_access_token())


def _track_uri(track_id: str) -> str:
    """Normalise a stored native_track_id into a Spotify track URI."""
    tid = (track_id or "").strip()
    if tid.startswith("spotify:track:"):
        return tid
    return f"spotify:track:{tid}"


class Spotify:
    def __init__(self, access_token: str):
        self.client = httpx.Client(
            timeout=20,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, **kw) -> dict:
        for attempt in range(6):
            r = self.client.get(url, **kw)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "2")) + 1)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def current_user_id(self) -> str:
        return self._get(f"{_API}/me")["id"]

    def list_my_playlists(self) -> list[dict]:
        out: list[dict] = []
        url = f"{_API}/me/playlists?limit=50"
        while url:
            data = self._get(url)
            for p in data.get("items", []):
                if p:
                    out.append({
                        "id": p["id"],
                        "name": p.get("name") or "Untitled",
                        "owner": (p.get("owner") or {}).get("display_name", ""),
                    })
            url = data.get("next")
        return out

    def _entries_from_items(self, items: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for item in items:
            t = (item or {}).get("track") or {}
            if not t.get("id"):
                continue  # local/null track
            # Some entries carry artists with a null `name` (e.g. local files,
            # podcast episodes surfaced in a playlist) — `.get("name", "")`
            # returns None there, not "", so guard each name before joining.
            artist = ", ".join((a or {}).get("name") or "" for a in (t.get("artists") or []))
            artist = artist.strip(", ").strip()
            title = (t.get("name") or "").strip()
            if not artist or not title:
                continue  # nothing usable — skip this track
            rows.append({
                "native_track_id": t["id"],
                "native_url": (t.get("external_urls") or {}).get("spotify", ""),
                "artist": artist,
                "title": title,
                "album": (t.get("album") or {}).get("name", ""),
                "position": len(rows),
            })
        return rows

    def playlist_tracks(self, playlist_id: str) -> list[dict]:
        rows: list[dict] = []
        url = f"{_API}/playlists/{playlist_id}/tracks?limit=100"
        while url:
            data = self._get(url)
            for r in self._entries_from_items(data.get("items", [])):
                r["position"] = len(rows)
                rows.append(r)
            url = data.get("next")
        return rows

    def saved_tracks(self) -> list[dict]:
        rows: list[dict] = []
        url = f"{_API}/me/tracks?limit=50"
        while url:
            data = self._get(url)
            for r in self._entries_from_items(data.get("items", [])):
                r["position"] = len(rows)
                rows.append(r)
            url = data.get("next")
        return rows

    # ── writes (push) ──────────────────────────────────────────────────────────

    def create_playlist(self, user_id: str, name: str, *, public: bool = False) -> str:
        r = self.client.post(
            f"{_API}/users/{user_id}/playlists",
            json={"name": name, "public": public},
        )
        r.raise_for_status()
        return r.json()["id"]

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> int:
        """Add tracks (by native id or uri) in batches of 100. Returns count added."""
        uris = [_track_uri(t) for t in track_ids if t]
        added = 0
        for i in range(0, len(uris), 100):
            batch = uris[i:i + 100]
            r = self.client.post(
                f"{_API}/playlists/{playlist_id}/tracks",
                json={"uris": batch},
            )
            r.raise_for_status()
            added += len(batch)
        return added

    def unfollow_playlist(self, playlist_id: str) -> None:
        """Remove a playlist from the user's account.

        Spotify has no hard-delete for playlists — even ones you own are removed
        by *unfollowing* them (`DELETE /playlists/{id}/followers`), which detaches
        the playlist from your library. The tracks (and your Liked Songs) are
        untouched. Idempotent: unfollowing an already-removed playlist is a no-op.
        """
        r = self.client.delete(f"{_API}/playlists/{playlist_id}/followers")
        r.raise_for_status()

    def clear_saved_tracks(self) -> int:
        """Remove every track from the user's Liked Songs. Returns the count removed.

        Fetches all saved track ids, then `DELETE /me/tracks` in batches of 50
        (the API max). Only Liked Songs is affected — playlists are untouched.
        DELETE carries a body, so it goes through `client.request` (httpx's
        `client.delete` takes no json= kwarg).
        """
        ids = [r["native_track_id"] for r in self.saved_tracks() if r.get("native_track_id")]
        removed = 0
        for i in range(0, len(ids), 50):
            batch = ids[i:i + 50]
            r = self.client.request("DELETE", f"{_API}/me/tracks", json={"ids": batch})
            r.raise_for_status()
            removed += len(batch)
        return removed
