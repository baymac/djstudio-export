#!/usr/bin/env python3
"""DJ CLI — unified tool:

  dj detect ...          Detect tracks from Instagram/radio/Mixcloud/YouTube/Podbean
  dj sync ...            Sync Apple Music → Beatport playlists
  dj playlist ...        Push a SQL query of enriched tracks to Beatport / rekordbox / DJ Studio

Beatport auth is handled transparently by connections/beatport.resolve_access_token
(env access token → env session cookie → browser cookie store). Sign into beatport.com
in your default browser (see connections/cookies.py); commands will refresh as needed.

Run `uv run dj_cli.py <command> --help` for details.
"""

import argparse
import warnings
from pathlib import Path

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

    return parser, detect_p, sync_p, playlist_p, course_p, vj_p


def main() -> None:
    parser, detect_p, sync_p, playlist_p, course_p, vj_p = _build_parser()
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
