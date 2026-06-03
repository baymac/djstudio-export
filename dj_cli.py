#!/usr/bin/env python3
"""DJ CLI — unified tool:

  dj detect ...          Detect tracks from Instagram/radio/Mixcloud/YouTube/Podbean
  dj sync ...            Capture Apple Music/Spotify/Beatport → enriched library
  dj enrich ...          Enrich detected + synced tracks → Beatport metadata + DJ Studio analysis
  dj set build ...       Build an energy-sequenced DJ set from the analysed library
  dj export ...          Push a stored set, or a SQL-curated subset, to Beatport / rekordbox
  dj version             Show the installed version
  dj update              Update dj to the latest release (or pull if in checkout)
  dj doctor              Check that all runtime dependencies are present

Beatport auth is handled transparently by connections/beatport.resolve_access_token
(env access token → env session cookie → browser cookie store). Sign into beatport.com
in your default browser (see connections/cookies.py); commands will refresh as needed.

Run `dj <command> --help` for details.
"""

import argparse
import platform
import sys
import warnings

warnings.filterwarnings("ignore", message=".*audioop.*", category=DeprecationWarning)

# macOS-only: fail early with a clear message on other platforms.
if platform.system() != "Darwin":
    print(
        "dj: unsupported OS — macOS is required (AppleScript, swiftc, DJ Studio, etc.).",
        file=sys.stderr,
    )
    sys.exit(1)

# Load .env before any subcommand imports (connections/spotify.py et al read
# env vars at import time).
from dotenv import load_dotenv
from paths import resolve_env_file

_env_file = resolve_env_file()
if _env_file:
    load_dotenv(_env_file, override=True)

from detect.cli import add_detect_subparser, dispatch as dispatch_detect
from sync.cli import add_sync_subparser, dispatch as dispatch_sync
from enrich.cli import add_enrich_subparser, dispatch as dispatch_enrich
from export.cli import add_export_subparser, dispatch as dispatch_export
from set.cli import add_set_subparser, dispatch as dispatch_set
from apps.course.cli import run_start as course_start, run_stop as course_stop
from apps.extension.cli import pack as extension_pack, list_extensions
from vj.cli import run_start as vj_start, run_stop as vj_stop, list_apps as vj_list_apps


def _version_string() -> str:
    """Return the current version, preferring importlib.metadata over VERSION file."""
    try:
        from importlib.metadata import version
        return version("dj")
    except Exception:
        pass
    try:
        from assets import _repo_root
        return (_repo_root() / "VERSION").read_text().strip()
    except Exception:
        return "unknown"


def _build_parser():
    ver = _version_string()
    parser = argparse.ArgumentParser(
        prog="dj",
        description="Track detection + Apple Music sync + set/SQL exports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dj detect instagram https://www.instagram.com/p/abc123/
  dj detect mixcloud https://www.mixcloud.com/djname/mixname/

  dj sync music pull             # capture everything from Apple Music → sync_tracks
  dj sync beatport pull          # Beatport playlists → enriched_tracks (checkpoint)
  dj sync music delete --playlists   # delete playlists from the app (dj.db kept)

  dj enrich metadata              # enrich detected + synced tracks → enriched_tracks
  dj enrich metadata --detect --dry-run    # only detected tracks
  dj enrich metadata --sync       # only synced tracks
  dj enrich analyse               # DJ Studio SDK analysis → enriched_tracks_analysis

  dj set build --list-archetypes
  dj set build --archetype club_night --duration 120
  dj set build --archetype party --name "Bday" --duration 90 --count 24 --save

  dj export set 42 --to bp_chart
  dj export beatport --query "SELECT beatport_id FROM enriched_tracks WHERE genre='Tech House'" --name "..."
  dj export rekordbox --query "..." --name "..."

  dj version
  dj update
  dj doctor
""",
    )
    parser.add_argument("--version", action="version", version=f"dj {ver}")
    sub = parser.add_subparsers(dest="command")

    detect_p = add_detect_subparser(sub)
    sync_p = add_sync_subparser(sub)
    enrich_p = add_enrich_subparser(sub)
    set_p = add_set_subparser(sub)
    export_p = add_export_subparser(sub)

    course_p = sub.add_parser("course", help="Start/stop the offline course viewer")
    course_sub = course_p.add_subparsers(dest="course_action")
    course_sub.add_parser("start", help="Start the viewer and open https://course.localhost")
    course_sub.add_parser("stop", help="Stop the viewer")

    vj_apps = vj_list_apps()
    vj_help = (
        f"Start/stop a VJ visualizer under vj/<name>/ "
        f"(available: {', '.join(vj_apps) or 'none yet'})"
    )
    vj_p = sub.add_parser("vj", help=vj_help)
    vj_p.add_argument("name", nargs="?", help="VJ app directory name under vj/")
    vj_p.add_argument("action", nargs="?", choices=["start", "stop"], help="start or stop")

    ext_names = list_extensions()
    ext_help = (
        f"Pack a Chrome extension under apps/<name>-extension/ "
        f"(available: {', '.join(ext_names) or 'none yet'})"
    )
    ext_p = sub.add_parser("extension", help=ext_help)
    ext_sub = ext_p.add_subparsers(dest="extension_action")
    ext_pack_p = ext_sub.add_parser("pack", help="Zip the extension to ~/Music/dj/extensions/")
    ext_pack_p.add_argument("name", help="Extension name (e.g. 1001T for apps/1001T-extension/)")

    # ── version ────────────────────────────────────────────────────────────
    sub.add_parser("version", help="Show the installed version")

    # ── update ─────────────────────────────────────────────────────────────
    upd_p = sub.add_parser(
        "update",
        help="Update dj to the latest release (or git pull when in checkout)",
    )
    upd_p.add_argument(
        "--check",
        action="store_true",
        help="Report whether an update is available without applying it",
    )
    upd_p.add_argument(
        "--force",
        action="store_true",
        help="Re-install even if already on the latest version",
    )

    # ── doctor ─────────────────────────────────────────────────────────────
    sub.add_parser("doctor", help="Check runtime dependencies and .env configuration")

    return parser, detect_p, sync_p, enrich_p, set_p, export_p, course_p, vj_p, ext_p


def main() -> None:
    parser, detect_p, sync_p, enrich_p, set_p, export_p, course_p, vj_p, ext_p = _build_parser()
    args = parser.parse_args()

    if args.command == "detect":
        dispatch_detect(args, detect_p)
    elif args.command == "sync":
        dispatch_sync(args, sync_p)
    elif args.command == "enrich":
        dispatch_enrich(args, enrich_p)
    elif args.command == "set":
        dispatch_set(args, set_p)
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
    elif args.command == "version":
        print(f"dj {_version_string()}")
    elif args.command == "update":
        from update import run_update
        run_update(check=args.check, force=args.force)
    elif args.command == "doctor":
        from doctor import run_doctor
        run_doctor()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
