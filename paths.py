"""Single source of truth for every file the dj tool reads or writes.

Layout under `~/Music/dj/`:

    dj.db                              SQLite — all tables
    logs/<command>/YYYY-MM-DD_<id>.log per-command log files
    state/                             session files, config, browser profile
    cache/musickit/                    Swift bridge build cache
    exports/                           default for export-* helpers
    backups/apple-music/               default for backup_apple_music helper
    backups/rekordbox/                 master.db pre-write backups

Each writer is responsible for its own `mkdir(parents=True, exist_ok=True)` —
this module just exposes path constants and small log helpers.

On import, if the legacy `~/Music/dj-tools/` directory exists and the new
`~/Music/dj/` does not, the legacy directory is renamed in place. Same
filesystem, atomic, no data duplication.
"""
from __future__ import annotations

import datetime
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, Tuple

DJ_DIR = Path.home() / "Music" / "dj"
_LEGACY_DIR = Path.home() / "Music" / "dj-tools"


def _migrate_legacy_location() -> None:
    if _LEGACY_DIR.exists() and not DJ_DIR.exists():
        DJ_DIR.parent.mkdir(parents=True, exist_ok=True)
        _LEGACY_DIR.rename(DJ_DIR)


_migrate_legacy_location()

DB_PATH = DJ_DIR / "dj.db"
LOGS_DIR = DJ_DIR / "logs"
STATE_DIR = DJ_DIR / "state"
CACHE_DIR = DJ_DIR / "cache"
EXPORTS_DIR = DJ_DIR / "exports"
BACKUPS_DIR = DJ_DIR / "backups"

# State files
IG_SESSION_FILE = STATE_DIR / "ig_session.json"
DETECT_CONFIG_FILE = STATE_DIR / "detect_config.json"

# Cache
MUSICKIT_CACHE_DIR = CACHE_DIR / "musickit"

COURSE_DIR = DJ_DIR / "course"
COURSE_PID_FILE = STATE_DIR / "course.pid"

# Exports & backups
APPLE_MUSIC_EXPORT_CSV = EXPORTS_DIR / "apple_music_export.csv"
APPLE_MUSIC_BACKUP_DIR = BACKUPS_DIR / "apple-music"
REKORDBOX_BACKUP_DIR = BACKUPS_DIR / "rekordbox"


def resolve_env_file() -> Path | None:
    """Return the path to the .env file to load, or None if none found.

    Search order (first match wins):
      1. $DJ_ENV_FILE env var (explicit override)
      2. ./.env (current working directory — checkout dev convenience)
      3. ~/Music/dj/.env (installed default; secrets live next to the DB)
      4. ~/.config/dj/.env (XDG-style fallback)

    Both ``dj_cli.py`` (load at startup) and ``connections/beatport.py``
    (token write-back) route through this so they always agree on which file
    to read from and persist to.
    """
    import os

    explicit = os.environ.get("DJ_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit)

    candidates = [
        Path(".env"),
        DJ_DIR / ".env",
        Path.home() / ".config" / "dj" / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def log_path(command: str, run_id: str | int) -> Path:
    """Return the log file path for one run of `command`. Creates the dir."""
    cmd_dir = LOGS_DIR / command
    cmd_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.date.today().isoformat()
    return cmd_dir / f"{date_str}_{run_id}.log"


def open_log(command: str, run_id: str | int | None = None) -> Tuple[Path, IO[str]]:
    """Open a fresh log file for a command run. Returns (path, file_handle)."""
    if run_id is None:
        run_id = datetime.datetime.now().strftime("%H%M%S")
    p = log_path(command, run_id)
    return p, p.open("w", encoding="utf-8")


@contextmanager
def command_logger(
    command: str, console, run_id: str | int | None = None,
) -> Iterator[Path]:
    """Capture every rich.Console call inside this block to a log file.

    Sets `console.record = True` for the duration; at exit, dumps `export_text`
    to logs/<command>/<date>_<run_id>.log. Use as:

        with command_logger("studio-analyse", console) as log_path:
            console.print(f"[dim]Log: {log_path}[/dim]")
            ...  # whatever the command does

    Survives exceptions — log is flushed in finally. Safe if console is None
    (no-op).
    """
    if run_id is None:
        run_id = datetime.datetime.now().strftime("%H%M%S")
    p = log_path(command, run_id)

    if console is None:
        yield p
        return

    prev_record = getattr(console, "record", False)
    console.record = True
    try:
        yield p
    finally:
        try:
            text = console.export_text(clear=True)
            p.write_text(text, encoding="utf-8")
        except Exception:
            pass
        console.record = prev_record
