"""Read cookies from local browser installs for a given domain.

Wraps `browser_cookie3` with two output shapes:
- `read_cookies_for_domain(domain, browser)` → list of Playwright-shaped dicts
  (drop-in for `playwright.context.add_cookies()`)
- `load_cookie_jar(domain, browser)` → `http.cookiejar.CookieJar`
  (drop-in for `httpx.Client(cookies=...)` or `requests`)

Supported browsers: brave, chrome, chromium, edge, opera, vivaldi, firefox, safari.

On macOS, Chromium-family cookies are AES-CBC encrypted with a key derived
from the Keychain (e.g. "Brave Safe Storage", "Chrome Safe Storage"). The
first call may pop a Keychain dialog — click "Always Allow" to silence
future prompts. Firefox uses NSS-encrypted SQLite; Safari uses a binary
plist. `browser_cookie3` handles each scheme internally.
"""
from __future__ import annotations

import http.cookiejar

SUPPORTED_BROWSERS = (
    "brave", "chrome", "chromium", "edge", "opera", "vivaldi", "firefox", "safari",
)
DEFAULT_BROWSER = "brave"


def _loader(browser: str):
    try:
        import browser_cookie3
    except ImportError as e:
        raise RuntimeError("browser-cookie3 is not installed; run: uv sync") from e

    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        raise ValueError(
            f"Unsupported browser: {browser!r}. "
            f"Choose from: {', '.join(SUPPORTED_BROWSERS)}."
        )
    return fn


def load_cookie_jar(domain: str, browser: str = DEFAULT_BROWSER) -> http.cookiejar.CookieJar:
    """Return a CookieJar for `domain` from the named browser's local store.

    `domain` is matched as a substring (browser_cookie3 calls SQL LIKE), so
    `"beatport.com"` matches `www.beatport.com`, `.beatport.com`, etc.
    """
    try:
        return _loader(browser)(domain_name=domain)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(
            f"Failed to read cookies from {browser} for {domain!r}: "
            f"{type(e).__name__}: {e}. "
            "If a macOS Keychain prompt appeared, click Allow / Always Allow."
        ) from e


def read_cookies_for_domain(
    domain: str,
    browser: str = DEFAULT_BROWSER,
) -> list[dict]:
    """Return Playwright-shaped cookie dicts for `domain` from `browser`.

    Each dict has: name, value, domain, path, expires, httpOnly, secure, sameSite.
    `expires` is Unix seconds (or -1 for session cookies, matching Playwright).
    """
    jar = load_cookie_jar(domain, browser)
    cookies: list[dict] = []
    for c in jar:
        http_only = False
        try:
            http_only = c.has_nonstandard_attr("HttpOnly") or c.has_nonstandard_attr("httponly")
        except Exception:
            pass
        cookies.append({
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain,
            "path": c.path or "/",
            "expires": float(c.expires) if c.expires else -1,
            "httpOnly": http_only,
            "secure": bool(c.secure),
            "sameSite": "Lax",
        })
    return cookies
