"""Beatport HTTP API client and token capture."""
from __future__ import annotations

import base64
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

API_ROOT = "https://api.beatport.com/v4"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# ---------- Auth ----------


_BEATPORT_SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"


def _read_beatport_cookies_from_browser() -> tuple[str, str]:
    """Read (session_cookie, cf_clearance) from the local browser cookie store.

    Browser defaults to whatever `connections.cookies.DEFAULT_BROWSER` is
    (currently Brave). Raises RuntimeError if the browser/cookies are
    unreadable; returns empty strings for individual cookies that aren't set.
    """
    from connections.cookies import read_cookies_for_domain
    cookies = read_cookies_for_domain("beatport.com")
    session = ""
    cf_clear = ""
    for c in cookies:
        if c["name"] == _BEATPORT_SESSION_COOKIE_NAME:
            session = c["value"]
        elif c["name"] == "cf_clearance":
            cf_clear = c["value"]
    if not session:
        raise RuntimeError(
            f"Cookie {_BEATPORT_SESSION_COOKIE_NAME!r} not found in the browser's "
            "Beatport store. Make sure you're logged into beatport.com."
        )
    return session, cf_clear


def _jwt_payload(token: str) -> dict:
    try:
        part = token.split()[-1].split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


_NEXTAUTH_SESSION_URL = "https://www.beatport.com/api/auth/session"


def refresh_via_session(session_cookie: str, *, verbose: bool = False) -> Optional[str]:
    """Refresh the Beatport access token using the NextAuth session cookie.

    Sends the __Secure-next-auth.session-token cookie (and BEATPORT_CF_CLEARANCE
    if present) to /api/auth/session via curl_cffi's Chrome 131 TLS impersonation.
    Plain httpx (urllib3 fingerprint) gets blocked by Cloudflare on /api/* routes
    even with a valid cf_clearance, because cf_clearance is bound to the
    originating client's JA3/JA4 — only a real-Chrome handshake satisfies it.

    NextAuth rotates the session cookie on every refresh; we persist any new
    Set-Cookie value so the next call works. cf_clearance also rotates
    occasionally — we persist that too.

    Returns 'Bearer <new_token>' or None on failure. verbose=True (or
    BEATPORT_DEBUG=1) prints the real cause to stderr.
    """
    import os
    if os.environ.get("BEATPORT_DEBUG"):
        verbose = True

    def _why(msg: str) -> None:
        if verbose:
            print(f"[refresh_via_session] {msg}", file=sys.stderr)

    from curl_cffi import requests as cffi_requests

    cookies: dict[str, str] = {_BEATPORT_SESSION_COOKIE_NAME: session_cookie}
    cf_clear = os.environ.get("BEATPORT_CF_CLEARANCE", "").strip()
    if cf_clear:
        cookies["cf_clearance"] = cf_clear

    _why(f"sending {len(cookies)} cookie(s): {sorted(cookies.keys())}")

    try:
        r = cffi_requests.get(
            _NEXTAUTH_SESSION_URL,
            cookies=cookies,
            headers={
                "accept": "application/json, text/plain, */*",
                "user-agent": USER_AGENT,
                "referer": "https://www.beatport.com/",
                "origin": "https://www.beatport.com",
            },
            impersonate="chrome131",
            timeout=30,
        )
    except Exception as e:
        _why(f"HTTP request failed: {type(e).__name__}: {e}")
        return None

    if r.status_code != 200:
        _why(f"HTTP {r.status_code}: {(r.text or '')[:200]!r}")
        if r.status_code == 403 and not cf_clear:
            _why("403 with no cf_clearance in env — log into beatport.com in your "
                 "default browser so the auto-resolve cascade can read a fresh one.")
        return None

    try:
        data = r.json()
    except Exception as e:
        _why(f"JSON parse failed: {e}; body head={(r.text or '')[:200]!r}")
        return None

    token_data = data.get("token") or {}
    err = token_data.get("error")
    if err:
        _why(f"NextAuth returned token.error={err!r} — server-side refresh chain is broken. "
             "Sign out and back into beatport.com in your default browser.")
        return None

    new_token = token_data.get("accessToken")
    if not new_token:
        _why(f"no accessToken in response; token keys={list(token_data.keys())}")
        return None

    bearer = f"Bearer {new_token}"
    if _jwt_payload(bearer).get("exp", 0) <= time.time():
        _why("accessToken returned but already expired by JWT exp")
        return None

    # Persist rotations.
    try:
        rotated_session = r.cookies.get(_BEATPORT_SESSION_COOKIE_NAME) or ""
    except Exception:
        rotated_session = ""
    try:
        rotated_cf = r.cookies.get("cf_clearance") or ""
    except Exception:
        rotated_cf = ""

    if rotated_session and rotated_session != session_cookie:
        save_token_to_env(bearer, rotated_session)
    else:
        save_token_to_env(bearer)
    if rotated_cf and rotated_cf != cf_clear:
        save_cf_clearance_to_env(rotated_cf)

    return bearer



def _set_env_key(key: str, value: str) -> None:
    try:
        from dotenv import set_key
        env_path = __import__("pathlib").Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            set_key(str(env_path), key, value)
    except Exception:
        pass


def save_token_to_env(token: str, session_cookie: Optional[str] = None) -> None:
    """Persist token (and optionally session cookie) back to .env."""
    _set_env_key("BEATPORT_ACCESS_TOKEN", token.removeprefix("Bearer ").strip())
    if session_cookie:
        _set_env_key("BEATPORT_SESSION_TOKEN", session_cookie)


def save_session_cookie_to_env(session_cookie: str) -> None:
    """Persist just the NextAuth session cookie."""
    if session_cookie:
        _set_env_key("BEATPORT_SESSION_TOKEN", session_cookie)


def save_cf_clearance_to_env(cf_clearance: str) -> None:
    """Persist the Cloudflare clearance cookie so /api/* refreshes survive CF."""
    if cf_clearance:
        _set_env_key("BEATPORT_CF_CLEARANCE", cf_clearance)
        # Also reflect into the running process so the very next refresh uses it.
        import os as _os
        _os.environ["BEATPORT_CF_CLEARANCE"] = cf_clearance


def resolve_access_token(
    *, force_refresh: bool = False, verbose: bool = False
) -> Optional[str]:
    """Return a valid 'Bearer <token>' or None.

    Cascade:
      1. BEATPORT_ACCESS_TOKEN env var (skipped if force_refresh)
      2. BEATPORT_SESSION_TOKEN cookie → refresh_via_session
      3. Browser cookie store → refresh_via_session
         (default browser per connections.cookies.DEFAULT_BROWSER)

    Persists any refreshed token (and rotated session/cf cookies) to .env.
    Use force_refresh=True from on_401 handlers so a server-side invalidation
    of an otherwise-unexpired JWT doesn't loop.
    """
    import os as _os
    import time as _time

    if not force_refresh:
        access_token = _os.environ.get("BEATPORT_ACCESS_TOKEN", "").strip()
        if access_token:
            if not access_token.startswith("Bearer "):
                access_token = f"Bearer {access_token}"
            if _jwt_payload(access_token).get("exp", 0) > _time.time():
                return access_token

    session_cookie = _os.environ.get("BEATPORT_SESSION_TOKEN", "").strip()
    if not session_cookie:
        try:
            from dotenv import dotenv_values
            session_cookie = (
                dotenv_values(".env").get("BEATPORT_SESSION_TOKEN", "") or ""
            ).strip()
        except Exception:
            pass
    if session_cookie:
        bearer = refresh_via_session(session_cookie, verbose=verbose)
        if bearer:
            return bearer

    try:
        browser_session, browser_cf = _read_beatport_cookies_from_browser()
    except RuntimeError:
        return None
    if browser_cf and browser_cf != _os.environ.get("BEATPORT_CF_CLEARANCE", "").strip():
        save_cf_clearance_to_env(browser_cf)
    if browser_session and browser_session != session_cookie:
        bearer = refresh_via_session(browser_session, verbose=verbose)
        if bearer:
            save_session_cookie_to_env(browser_session)
            return bearer
    return None


def make_client(token: str) -> httpx.Client:
    return httpx.Client(
        timeout=30,
        headers={
            "authorization": token,
            "content-type": "application/json",
            "accept": "application/json, text/plain, */*",
            "user-agent": USER_AGENT,
            "origin": "https://www.beatport.com",
            "referer": "https://www.beatport.com/",
        },
    )


# ---------- API client ----------

class AuthExpiredError(Exception):
    """Raised when a Beatport token is expired and cannot be refreshed."""


@dataclass
class Beatport:
    client: httpx.Client
    on_401: Optional[Callable[[], None]] = field(default=None)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        for attempt in range(6):
            r = self.client.request(method, url, **kw)
            if r.status_code == 429:
                if attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
            elif r.status_code == 401 and self.on_401 and attempt == 0:
                self.on_401()
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r  # unreachable

    def get_track(self, track_id: int) -> Optional[dict]:
        """GET /catalog/tracks/{id}/ — full track record including sample_url."""
        try:
            return self._request(
                "GET", f"{API_ROOT}/catalog/tracks/{track_id}/"
            ).json()
        except AuthExpiredError:
            raise
        except Exception:
            return None

    def preview_url(self, track_id: int) -> Optional[str]:
        """Return the 30s preview MP3 URL for a track, or None."""
        rec = self.get_track(track_id)
        if not rec:
            return None
        return (
            rec.get("sample_url")
            or rec.get("sample_mp3_url")
            or (rec.get("sample") or {}).get("url")
        )

    def search_tracks(
        self, query: str, per_page: int = 5, debug: bool = False
    ) -> Optional[list[dict]]:
        """Search catalog.
        Returns list of track dicts (possibly empty), or None if request failed.
        Empty list = genuinely no results. None = request error (retry next run).
        """
        try:
            data = self._request(
                "GET",
                f"{API_ROOT}/catalog/search/",
                params={"q": query, "type": "tracks", "page": 1, "per_page": per_page},
            ).json()
            if isinstance(data, list):
                tracks = data
            else:
                tracks_raw = data.get("tracks", [])
                tracks = tracks_raw if isinstance(tracks_raw, list) else tracks_raw.get("data", [])
        except AuthExpiredError:
            raise
        except Exception as e:
            if debug:
                print(f"[search primary] {query!r}: {type(e).__name__}: {e}", file=sys.stderr)
            return None

        if tracks:
            return tracks

        try:
            data = self._request(
                "GET",
                f"{API_ROOT}/catalog/tracks/",
                params={"q": query, "page": 1, "per_page": per_page},
            ).json()
            if isinstance(data, list):
                return data
            return data.get("results", [])
        except AuthExpiredError:
            raise
        except Exception as e:
            if debug:
                print(f"[search fallback] {query!r}: {type(e).__name__}: {e}", file=sys.stderr)
            return None


    def list_my_playlists(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            data = self._request(
                "GET", f"{API_ROOT}/my/playlists/?page={page}&per_page=50"
            ).json()
            out.extend(data["results"])
            if not data.get("next"):
                break
            page += 1
        return out

    def create_playlist(self, name: str) -> dict:
        return self._request(
            "POST",
            f"{API_ROOT}/my/playlists/",
            json={"name": name},
        ).json()

    def list_track_ids(self, playlist_id: int) -> set[int]:
        try:
            data = self._request(
                "GET", f"{API_ROOT}/my/playlists/{playlist_id}/tracks/ids/"
            ).json()
            if "results" in data:
                return {item.get("track_id") or item.get("id") for item in data["results"]}
            if "track_ids" in data:
                return set(data["track_ids"])
        except Exception:
            pass
        return self._list_track_ids_paged(playlist_id)

    def _list_track_ids_paged(self, playlist_id: int) -> set[int]:
        ids: set[int] = set()
        page = 1
        while True:
            data = self._request(
                "GET",
                f"{API_ROOT}/my/playlists/{playlist_id}/tracks/"
                f"?page={page}&per_page=100",
            ).json()
            for entry in data["results"]:
                tid = entry.get("track_id") or entry.get("track", {}).get("id")
                if tid:
                    ids.add(tid)
            if not data.get("next"):
                break
            page += 1
        return ids

    def list_playlist_items(self, playlist_id: int) -> list[dict]:
        """Return raw playlist track entries, each containing item `id` and catalog `track_id`."""
        items: list[dict] = []
        page = 1
        while True:
            data = self._request(
                "GET",
                f"{API_ROOT}/my/playlists/{playlist_id}/tracks/",
                params={"page": page, "per_page": 100},
            ).json()
            items.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return items

    def add_track(self, dest_id: int, track_id: int) -> dict:
        return self._request(
            "POST",
            f"{API_ROOT}/my/playlists/{dest_id}/tracks/bulk/",
            json={"track_ids": [track_id]},
        ).json()

    def delete_track(self, playlist_id: int, track_id: int) -> None:
        """Remove a track from a playlist using its internal playlist item ID."""
        items = self.list_playlist_items(playlist_id)
        item_id: Optional[int] = None
        for item in items:
            catalog_id = item.get("track_id") or item.get("track", {}).get("id")
            if catalog_id == track_id:
                item_id = item.get("id")
                break

        if item_id is None:
            raise ValueError(
                f"Track {track_id} not found in playlist {playlist_id}."
            )

        self._request(
            "DELETE",
            f"{API_ROOT}/my/playlists/{playlist_id}/tracks/bulk/",
            json={"item_ids": [item_id]},
        )
