#!/usr/bin/env python3
"""DJ CLI — unified tool:

  dj detect ...          Detect tracks from Instagram/radio/Mixcloud/YouTube/Podbean
  dj sync ...            Sync Apple Music → Beatport playlists
  dj playlist ...        Push a SQL query of enriched tracks to Beatport / rekordbox / DJ Studio
  dj login-beatport ...  Refresh Beatport tokens

Run `uv run dj_cli.py <command> --help` for details.
"""

import argparse
import sys
import warnings
from pathlib import Path
from typing import Optional

warnings.filterwarnings("ignore", message=".*audioop.*", category=DeprecationWarning)

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=True)

from detect.cli import add_detect_subparser, dispatch as dispatch_detect
from sync.cli import add_sync_subparser, dispatch as dispatch_sync
from playlist.cli import add_playlist_subparser, dispatch as dispatch_playlist
from apps.course.cli import run_start as course_start, run_stop as course_stop
from vj.cli import run_start as vj_start, run_stop as vj_stop, list_apps as vj_list_apps


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="dj_cli.py",
        description="Track detection + Apple Music sync + curated playlist pushes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run dj_cli.py detect instagram https://www.instagram.com/p/abc123/
  uv run dj_cli.py detect mixcloud https://www.mixcloud.com/djname/mixname/
  uv run dj_cli.py detect history
  uv run dj_cli.py detect enrich --dry-run

  uv run dj_cli.py sync music-beatport sync --library

  uv run dj_cli.py playlist beatport --query "SELECT beatport_id FROM enriched_tracks_full WHERE genre='Tech House' AND mik_nrg>=7" --name "Peak Tech House"
  uv run dj_cli.py playlist rekordbox --query "..." --name "..."
""",
    )
    sub = parser.add_subparsers(dest="command")

    detect_p = add_detect_subparser(sub)
    sync_p = add_sync_subparser(sub)
    playlist_p = add_playlist_subparser(sub)

    course_p = sub.add_parser("course", help="Start/stop the offline course viewer")
    course_sub = course_p.add_subparsers(dest="course_action")
    course_sub.add_parser("start", help=f"Start the viewer and open https://course.localhost")
    course_sub.add_parser("stop", help="Stop the viewer")

    vj_apps = vj_list_apps()
    vj_help = f"Start/stop a VJ visualizer under vj/<name>/ (available: {', '.join(vj_apps) or 'none yet'})"
    vj_p = sub.add_parser("vj", help=vj_help)
    vj_p.add_argument("name", nargs="?", help="VJ app directory name under vj/")
    vj_p.add_argument("action", nargs="?", choices=["start", "stop"], help="start or stop")

    lb_p = sub.add_parser(
        "login-beatport",
        help="Fetch a fresh Beatport token and save it to .env",
    )
    mode = lb_p.add_mutually_exclusive_group()
    mode.add_argument("--cookie", action="store_true",
                      help="Refresh via BEATPORT_SESSION_TOKEN cookie")
    mode.add_argument("--brave", action="store_true",
                      help="Read session cookie from Brave's local store (no browser window needed)")

    return parser, detect_p, sync_p, playlist_p, lb_p, course_p, vj_p


def _handle_login_beatport(args) -> None:
    from connections import beatport as bp_api
    from rich.console import Console
    console = Console()

    def _save_and_report(token: str, session: Optional[str] = None) -> None:
        bp_api.save_token_to_env(token, session)
        import os; os.environ["BEATPORT_ACCESS_TOKEN"] = token.removeprefix("Bearer ").strip()
        extra = " + session cookie" if session else ""
        console.print(f"[green]Token{extra} saved to .env[/green] — expires in ~10 min, session cookie will auto-refresh.")

    def _refresh_from_browser() -> Optional[tuple[str, str]]:
        """Read session+cf_clearance from Brave, persist cf_clearance, refresh.

        Returns (token, session_cookie) on success or None on failure.
        """
        try:
            session_cookie, cf_clear = bp_api._read_beatport_cookies_from_browser()
        except RuntimeError as e:
            console.print(f"[red]Brave cookie read failed:[/red] {e}")
            return None
        if cf_clear:
            bp_api.save_cf_clearance_to_env(cf_clear)
        token = bp_api.refresh_via_session(session_cookie, verbose=True)
        if not token:
            return None
        return token, session_cookie

    if not args.cookie and not getattr(args, "brave", False):
        import os, time as _t
        current = os.environ.get("BEATPORT_ACCESS_TOKEN", "").strip()
        if current:
            if not current.startswith("Bearer "):
                current = f"Bearer {current}"
            remaining = int(bp_api._jwt_payload(current).get("exp", 0) - _t.time())
            if remaining > 0:
                console.print(f"[green]Token still valid[/green] — expires in {remaining}s. Use --brave or --cookie to force refresh.")
                return

    if getattr(args, "brave", False):
        result = _refresh_from_browser()
        if not result:
            console.print("[red]Brave cookie refresh failed — log into beatport.com in Brave, then re-run.[/red]")
            sys.exit(1)
        token, session_cookie = result
        _save_and_report(token, session_cookie)
        return

    if args.cookie:
        session_cookie = __import__("os").environ.get("BEATPORT_SESSION_TOKEN", "").strip()
        if not session_cookie:
            console.print("[red]BEATPORT_SESSION_TOKEN not set in .env[/red]")
            sys.exit(1)
        token = bp_api.refresh_via_session(session_cookie, verbose=True)
        if not token:
            console.print("[red]Session cookie refresh failed — cookie may be expired.[/red]")
            sys.exit(1)
        _save_and_report(token)
        return

    # No flag — auto mode: try session cookie, then Brave store
    import os as _os
    session_cookie = _os.environ.get("BEATPORT_SESSION_TOKEN", "").strip()
    if session_cookie:
        token = bp_api.refresh_via_session(session_cookie, verbose=True)
        if token:
            _save_and_report(token)
            return
        console.print("[yellow]Session cookie refresh failed — trying Brave cookie store…[/yellow]")

    result = _refresh_from_browser()
    if result:
        token, browser_session = result
        _save_and_report(token, browser_session)
        return

    console.print(
        "[red]Could not get a valid Beatport token.[/red]\n"
        "Log into beatport.com in Brave (sign out and back in if needed to rotate "
        "the NextAuth session), then run [bold]dj login-beatport[/bold] again."
    )
    sys.exit(1)


def main() -> None:
    parser, detect_p, sync_p, playlist_p, lb_p, course_p, vj_p = _build_parser()
    args = parser.parse_args()

    if args.command == "detect":
        dispatch_detect(args, detect_p)
    elif args.command == "sync":
        dispatch_sync(args, sync_p)
    elif args.command == "playlist":
        dispatch_playlist(args, playlist_p)
    elif args.command == "course":
        if args.course_action == "start":
            course_start()
        elif args.course_action == "stop":
            course_stop()
        else:
            course_p.print_help()
    elif args.command == "vj":
        if not args.name or not args.action:
            vj_p.print_help()
            apps = vj_list_apps()
            if apps:
                print(f"\nAvailable VJ apps: {', '.join(apps)}")
            return
        if args.action == "start":
            vj_start(args.name)
        else:
            vj_stop(args.name)
    elif args.command == "login-beatport":
        _handle_login_beatport(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
