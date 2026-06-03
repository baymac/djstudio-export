import argparse

_build_p = None  # populated by add_set_subparser(); used by dispatch()


def add_set_subparser(parent):
    global _build_p

    from helpers.build_set import ARCHETYPES, METHODS

    set_p = parent.add_parser("set", help="Build and manage DJ sets")
    set_sub = set_p.add_subparsers(dest="set_command")

    _build_p = set_sub.add_parser(
        "build",
        help="Build an energy-sequenced set from the analysed library",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Build a DJ set using an energy-curve archetype.\n\n"
            "Archetypes: " + ", ".join(ARCHETYPES)
        ),
    )
    _build_p.add_argument("--archetype", help="set archetype key (see --list-archetypes)")
    _build_p.add_argument("--name", help="set name (required with --save)")
    _build_p.add_argument("--mood", default="", help="free-text mood/setting (stored)")
    _build_p.add_argument("--duration", type=int, help="set duration in minutes")
    _build_p.add_argument(
        "--count", type=int,
        help="target track count (clamped to [duration/5, duration/2])",
    )
    _build_p.add_argument("--genres", help="comma-separated genres (overrides archetype defaults)")
    _build_p.add_argument(
        "--date-blend",
        help=(
            'JSON list of {"from","to","ratio","label"} release-date buckets. '
            "Omit for the default 75/12.5/12.5 new/recent/classic mix."
        ),
    )
    _build_p.add_argument(
        "--method", choices=METHODS, default=None,
        help="harmonic mixing method: fuzzy (safe/mixtape) or mood (playful/live). "
             "Defaults to the archetype's suggested method.",
    )
    _build_p.add_argument(
        "--diversity", type=float, default=None,
        help="key-diversity 0..1: anti-monotony pressure (defaults to archetype's).",
    )
    _build_p.add_argument(
        "--exclude-used", action="store_true",
        help="exclude tracks already used in ANY previously-built set",
    )
    _build_p.add_argument("--seed-id", type=int, help="force this beatport_id first")
    _build_p.add_argument("--json", action="store_true", help="emit the built set as JSON")
    _build_p.add_argument("--save", action="store_true", help="persist to dj_sets, print set_id")
    _build_p.add_argument("--list-archetypes", action="store_true",
                          help="list all archetypes and exit")
    _build_p.add_argument("--list-genres", action="store_true",
                          help="list genres in the analysed library and exit")

    return set_p


def dispatch(args, set_p):
    if args.set_command == "build":
        from helpers.build_set import run as _build_run
        _build_run(args, _build_p)
    else:
        set_p.print_help()
