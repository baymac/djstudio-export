"""dj doctor — preflight check for all runtime dependencies.

Checks are split into required (all commands need them) and per-feature
(only relevant commands fail if absent).  Each failing check prints the
exact fix-it command so the output is actionable.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


# ─────────────────────────────────── helpers ─────────────────────────────────


def _cmd_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_silent(*args: str) -> bool:
    try:
        r = subprocess.run(list(args), capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _python_version_ok() -> bool:
    return sys.version_info >= (3, 11)


# ─────────────────────────────────── checks ──────────────────────────────────


def _check_uv() -> tuple[bool, str]:
    ok = _cmd_exists("uv")
    fix = "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    return ok, fix


def _check_node() -> tuple[bool, str]:
    ok = _cmd_exists("node") and _cmd_exists("npm") and _cmd_exists("npx")
    fix = "Install Node.js (includes npm/npx): https://nodejs.org or `brew install node`"
    return ok, fix


def _check_portless() -> tuple[bool, str]:
    # portless is used as a dev-server HTTPS proxy for dj course / dj vj.
    ok = _run_silent("npx", "--yes", "portless", "--version")
    fix = "portless is installed on first `dj course start` via npx (no manual step needed)"
    return ok, fix


def _check_swiftc() -> tuple[bool, str]:
    ok = _cmd_exists("swiftc")
    fix = "Install Xcode Command Line Tools: xcode-select --install"
    return ok, fix


def _check_dj_studio() -> tuple[bool, str]:
    app = Path("/Applications/DJ.Studio.app")
    ok = app.is_dir()
    fix = "Install DJ Studio from https://dj.studio (required for `dj enrich analyse`)"
    return ok, fix


def _check_playwright() -> tuple[bool, str]:
    try:
        import playwright  # noqa: F401
        ok = True
    except ImportError:
        ok = False
    fix = (
        "Install playwright browser: "
        "uv run playwright install chromium   (or: pip install playwright && playwright install chromium)"
    )
    return ok, fix


def _check_env_file() -> tuple[bool, str]:
    from paths import resolve_env_file
    ef = resolve_env_file()
    if ef is None:
        return False, (
            "No .env file found.  Create one at ~/Music/dj/.env with:\n"
            "  BEATPORT_SESSION_TOKEN=<your-token>\n"
            "  (Sign in at beatport.com, open DevTools → Application → Cookies → "
            "copy __Secure-next-auth.session-token)"
        )
    # Check that at least one Beatport token is present.
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(str(ef))
        if not vals.get("BEATPORT_SESSION_TOKEN") and not vals.get("BEATPORT_ACCESS_TOKEN"):
            return False, (
                f".env found at {ef} but BEATPORT_SESSION_TOKEN is missing.\n"
                "  Sign in to beatport.com, open DevTools → Application → Cookies → "
                "copy __Secure-next-auth.session-token → add it to the .env."
            )
    except Exception:
        pass
    return True, f".env loaded from {ef}"


def _check_dj_tools_conflict() -> tuple[bool, str]:
    """Warn if the old 'dj-tools' dist is still installed alongside 'dj'."""
    try:
        import importlib.metadata as _im
        _im.version("dj-tools")
        # If we get here, the old dist exists.
        return False, (
            "Old 'dj-tools' distribution is still installed — this may shadow the new 'dj'.\n"
            "  Fix: uv tool uninstall dj-tools"
        )
    except Exception:
        return True, ""


def _check_multiple_dj_on_path() -> tuple[bool, str]:
    result = subprocess.run(
        ["which", "-a", "dj"], capture_output=True, text=True
    )
    paths = list(dict.fromkeys(  # deduplicate while preserving order
        l.strip() for l in result.stdout.strip().splitlines() if l.strip()
    ))
    if len(paths) > 1:
        listed = "\n  ".join(paths)
        return False, (
            f"Multiple 'dj' binaries on PATH:\n  {listed}\n"
            "  This may cause the wrong version to run.  Remove or deactivate extras."
        )
    return True, ""


# ─────────────────────────────────── runner ──────────────────────────────────


def run_doctor() -> None:
    checks = [
        # (label, required_for, check_fn)
        ("Python ≥ 3.11",       "all commands",         lambda: (_python_version_ok(), "Upgrade Python to 3.11+")),
        ("uv",                   "install / update",     _check_uv),
        ("Node / npm / npx",     "dj course, dj vj",     _check_node),
        ("portless proxy",       "dj course, dj vj",     _check_portless),
        ("swiftc / Xcode CLT",   "dj sync music",        _check_swiftc),
        ("DJ Studio.app",        "dj enrich analyse",    _check_dj_studio),
        ("Playwright browser",   "dj detect (audio)",    _check_playwright),
        (".env / Beatport token","dj enrich, dj export", _check_env_file),
        ("dj-tools conflict",    "PATH hygiene",         _check_dj_tools_conflict),
        ("single dj on PATH",    "PATH hygiene",         _check_multiple_dj_on_path),
    ]

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("Check")
    table.add_column("Needed for")
    table.add_column("Status")

    all_ok = True
    failures: list[tuple[str, str]] = []

    for label, scope, fn in checks:
        ok, fix = fn()
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        table.add_row(label, scope, status)
        if not ok:
            all_ok = False
            failures.append((label, fix))

    console.print()
    console.print(table)

    if failures:
        console.print()
        for label, fix in failures:
            console.print(f"[bold red]{label}[/bold red]")
            for line in fix.splitlines():
                console.print(f"  {line}")
            console.print()
    else:
        console.print("\n[green]All checks passed.[/green]")

    # Show .env search order for reference.
    from paths import DJ_DIR
    console.print(
        "[dim].env search order: $DJ_ENV_FILE → ./.env → "
        f"{DJ_DIR / '.env'} → ~/.config/dj/.env[/dim]"
    )

    if not all_ok:
        sys.exit(1)
