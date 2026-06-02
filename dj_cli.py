#!/usr/bin/env python3
"""DJ CLI — unified tool:

  dj detect ...          Detect tracks from Instagram/radio/Mixcloud/YouTube/Podbean
  dj sync ...            Capture Apple Music/Spotify/Beatport → enriched library
  dj enrich ...          Enrich detected + synced tracks → Beatport metadata + DJ Studio analysis
  dj export ...          Push a stored set, or a SQL-curated subset, to Beatport / rekordbox

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
from enrich.cli import add_enrich_subparser, dispatch as dispatch_enrich
from export.cli import add_export_subparser, dispatch as dispatch_export
from apps.course.cli import run_start as course_start, run_stop as course_stop
from apps.extension.cli import pack as extension_pack, list_extensions
from vj.cli import run_start as vj_start, run_stop as vj_stop, list_apps as vj_list_apps


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="dj_cli.py",
        description="Track detection + Apple Music sync + set/SQL exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run dj_cli.py detect instagram https://www.instagram.com/p/abc123/
  uv run dj_cli.py detect mixcloud https://www.mixcloud.com/djname/mixname/

  uv run dj_cli.py sync music                 # capture all Apple Music playlists → sync_tracks
  uv run dj_cli.py sync beatport               # Beatport playlists → enriched_tracks (checkpoint)
  uv run dj_cli.py sync music playlist delete --playlists   # delete playlists from the app (dj.db kept)

  uv run dj_cli.py enrich                       # enrich detected + synced tracks → enriched_tracks
  uv run dj_cli.py enrich --detect --dry-run    # only detected tracks
  uv run dj_cli.py enrich --sync                # only synced tracks
  uv run dj_cli.py enrich analyse               # DJ Studio SDK analysis → enriched_tracks_analysis

  uv run dj_cli.py export set 42 --to bp_chart
  uv run dj_cli.py export beatport --query "SELECT beatport_id FROM enriched_tracks WHERE genre='Tech House' AND bpm BETWEEN 124 AND 128" --name "Peak Tech House"
  uv run dj_cli.py export rekordbox --query "..." --name "..."
""",
    )
    sub = parser.add_subparsers(dest="command")

    detect_p = add_detect_subparser(sub)
    sync_p = add_sync_subparser(sub)
    enrich_p = add_enrich_subparser(sub)
    export_p = add_export_subparser(sub)

    course_p = sub.add_parser("course", help="Start/stop the offline course viewer")
    course_sub = course_p.add_subparsers(dest="course_action")
    course_sub.add_parser("start", help=f"Start the viewer and open https://course.localhost")
    course_sub.add_parser("stop", help="Stop the viewer")

    vj_apps = vj_list_apps()
    vj_help = f"Start/stop a VJ visualizer under vj/<name>/ (available: {', '.join(vj_apps) or 'none yet'})"
    vj_p = sub.add_parser("vj", help=vj_help)
    vj_p.add_argument("name", nargs="?", help="VJ app directory name under vj/")
    vj_p.add_argument("action", nargs="?", choices=["start", "stop"], help="start or stop")

    ext_names = list_extensions()
    ext_help = f"Pack a Chrome extension under apps/<name>-extension/ (available: {', '.join(ext_names) or 'none yet'})"
    ext_p = sub.add_parser("extension", help=ext_help)
    ext_sub = ext_p.add_subparsers(dest="extension_action")
    ext_pack_p = ext_sub.add_parser("pack", help="Zip the extension to ~/Music/dj/extensions/")
    ext_pack_p.add_argument("name", help="Extension name (e.g. 1001T for apps/1001T-extension/)")

    return parser, detect_p, sync_p, enrich_p, export_p, course_p, vj_p, ext_p


def main() -> None:
    parser, detect_p, sync_p, enrich_p, export_p, course_p, vj_p, ext_p = _build_parser()
    args = parser.parse_args()

    if args.command == "detect":
        dispatch_detect(args, detect_p)
    elif args.command == "sync":
        dispatch_sync(args, sync_p)
    elif args.command == "enrich":
        dispatch_enrich(args, enrich_p)
    elif args.command == "export":
        dispatch_export(args, export_p)
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
    elif args.command == "extension":
        if args.extension_action == "pack":
            extension_pack(args.name)
        else:
            ext_p.print_help()
            names = list_extensions()
            if names:
                print(f"\nAvailable extensions: {', '.join(names)}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
