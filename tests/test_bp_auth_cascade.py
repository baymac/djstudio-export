"""Regression tests for connections/beatport.py resolve_access_token cascade.

Covers the bug where browser_session == session_cookie caused step 3 to be
skipped even after fresh cf_clearance was obtained from the browser.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_env(access_token="", session_token="", cf_clearance=""):
    return {
        "BEATPORT_ACCESS_TOKEN": access_token,
        "BEATPORT_SESSION_TOKEN": session_token,
        "BEATPORT_CF_CLEARANCE": cf_clearance,
        "BEATPORT_DEBUG": "",
    }


def test_step3_retries_when_browser_session_matches_env_session():
    """Regression: resolve_access_token must retry refresh when browser_session ==
    session_cookie, because the browser may provide a fresh cf_clearance that
    unblocks a refresh that previously 403'd in step 2."""
    import connections.beatport as bp

    same_cookie = "same-session-cookie"
    fresh_cf = "fresh-cf-clearance"

    env = _make_env(session_token=same_cookie, cf_clearance="stale-cf")

    with (
        patch.dict("os.environ", env, clear=False),
        # Step 2 fails (stale cf_clearance → 403)
        patch.object(bp, "refresh_via_session", side_effect=[None, "Bearer token123"]) as mock_refresh,
        patch.object(bp, "_read_beatport_cookies_from_browser",
                     return_value=(same_cookie, fresh_cf)),
        patch.object(bp, "save_cf_clearance_to_env") as mock_save_cf,
        patch.object(bp, "save_session_cookie_to_env") as mock_save_session,
        patch.object(bp, "_jwt_payload", return_value={}),  # access token absent
    ):
        result = bp.resolve_access_token()

    assert result == "Bearer token123", "Step 3 should retry and succeed with fresh cf_clearance"
    assert mock_refresh.call_count == 2, "refresh_via_session must be called twice"
    mock_save_cf.assert_called_once_with(fresh_cf)
    # Session cookie was same as env — should NOT be re-saved
    mock_save_session.assert_not_called()


def test_step3_saves_session_when_browser_session_differs():
    """When the browser has a newer session cookie, it should be persisted."""
    import connections.beatport as bp

    env_cookie = "old-session-cookie"
    browser_cookie = "newer-session-cookie"

    env = _make_env(session_token=env_cookie)

    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(bp, "refresh_via_session", side_effect=[None, "Bearer token456"]),
        patch.object(bp, "_read_beatport_cookies_from_browser",
                     return_value=(browser_cookie, "")),
        patch.object(bp, "save_cf_clearance_to_env"),
        patch.object(bp, "save_session_cookie_to_env") as mock_save_session,
        patch.object(bp, "_jwt_payload", return_value={}),
    ):
        result = bp.resolve_access_token()

    assert result == "Bearer token456"
    mock_save_session.assert_called_once_with(browser_cookie)


def test_step3_skips_when_browser_cookie_unreadable():
    """RuntimeError from _read_beatport_cookies_from_browser returns None cleanly."""
    import connections.beatport as bp

    env = _make_env(session_token="some-cookie")

    with (
        patch.dict("os.environ", env, clear=False),
        patch.object(bp, "refresh_via_session", return_value=None),
        patch.object(bp, "_read_beatport_cookies_from_browser",
                     side_effect=RuntimeError("Keychain denied")),
        patch.object(bp, "_jwt_payload", return_value={}),
    ):
        result = bp.resolve_access_token()

    assert result is None
