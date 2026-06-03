"""dj update — keep the dj CLI up-to-date.

Two modes depending on how dj is running:

  checkout  (source tree):  git pull (+ uv sync if uv.lock changed).
            Aborts if the working tree is dirty or the branch has diverged.
  installed (uv tool):       queries the latest GitHub Release tag, compares
            to the running version, and re-installs via
            ``uv tool install --force git+https://...@<tag>``.

``dj update --check`` reports availability without writing anything.
``dj update --force`` re-installs even when already on the latest.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from rich.console import Console
from assets import running_from_checkout

console = Console()

GITHUB_REPO = "baymac/dj"
INSTALL_URL = f"git+https://github.com/{GITHUB_REPO}.git"


# ─────────────────────────────────── version helpers ─────────────────────────


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into a comparable int tuple."""
    v = v.lstrip("v").strip()
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def _current_version() -> str:
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


# ─────────────────────────────── GitHub Release API ──────────────────────────


def _latest_release_tag() -> Optional[str]:
    """Return the latest GitHub Release tag (e.g. 'v0.1.7'), or None on error."""
    import urllib.request
    import json

    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dj-cli/update"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        tag = data.get("tag_name", "").strip()
        return tag or None
    except Exception as exc:
        return None


def _check_for_update() -> tuple[Optional[str], Optional[str]]:
    """Return (current_version, latest_tag) — latest_tag is None on network error."""
    current = _current_version()
    latest = _latest_release_tag()
    return current, latest


# ─────────────────────────────────── checkout mode ───────────────────────────


def _run_checkout_update(check: bool) -> None:
    from assets import _repo_root

    repo = _repo_root()

    # Guard: working tree must be clean (skip for --check, which is read-only).
    if not check:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True,
        )
        if dirty.stdout.strip():
            console.print(
                "[red]Cannot update:[/red] working tree has uncommitted changes.\n"
                "Stash or commit them first, then re-run [bold]dj update[/bold]."
            )
            sys.exit(1)

    # Guard: must be on a tracking branch, not detached or ahead.
    branch_out = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    branch = branch_out.stdout.strip()
    if branch == "HEAD":
        console.print(
            "[red]Cannot update:[/red] HEAD is detached. "
            "Check out the main branch first."
        )
        sys.exit(1)

    # Check if there's a remote tracking branch.
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
        cwd=repo, capture_output=True, text=True,
    )
    if upstream.returncode != 0:
        console.print(
            f"[red]Cannot update:[/red] branch '{branch}' has no upstream tracking branch."
        )
        sys.exit(1)

    # Check divergence (local commits ahead).
    ahead_out = subprocess.run(
        ["git", "rev-list", "--count", f"@{{upstream}}..HEAD"],
        cwd=repo, capture_output=True, text=True,
    )
    ahead = int(ahead_out.stdout.strip() or "0")
    if ahead > 0:
        console.print(
            f"[red]Cannot update:[/red] branch '{branch}' has {ahead} local "
            "commit(s) not on the remote. Push or reset first."
        )
        sys.exit(1)

    # Check if we're behind.
    behind_out = subprocess.run(
        ["git", "fetch", "--dry-run"],
        cwd=repo, capture_output=True, text=True,
    )
    behind = subprocess.run(
        ["git", "rev-list", "--count", "HEAD..@{upstream}"],
        cwd=repo, capture_output=True, text=True,
    )
    n_behind = int(behind.stdout.strip() or "0")

    if check:
        if n_behind == 0:
            console.print("[green]Already up-to-date.[/green] (checkout)")
        else:
            console.print(
                f"[yellow]Update available:[/yellow] {n_behind} commit(s) ahead on remote. "
                "Run [bold]dj update[/bold] to pull."
            )
        return

    if n_behind == 0:
        console.print("[green]Already up-to-date.[/green] (checkout)")
        return

    console.print(f"[cyan]Pulling {n_behind} commit(s)…[/cyan]")
    subprocess.run(["git", "fetch"], cwd=repo, check=True)

    # Remember the current lock hash before pull.
    lock_before = _file_hash(repo / "uv.lock")
    subprocess.run(["git", "merge", "--ff-only", "@{upstream}"], cwd=repo, check=True)
    lock_after = _file_hash(repo / "uv.lock")

    if lock_before != lock_after:
        console.print("[cyan]uv.lock changed — running uv sync…[/cyan]")
        subprocess.run(["uv", "sync"], cwd=repo, check=True)

    new_ver = _current_version()
    console.print(f"[green]Updated to {new_ver}.[/green]")


def _file_hash(path) -> str:
    import hashlib
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:
        return ""


# ─────────────────────────────────── installed mode ──────────────────────────


def _run_installed_update(check: bool, force: bool) -> None:
    current, latest = _check_for_update()

    if latest is None:
        console.print(
            "[yellow]Could not reach GitHub to check for updates.[/yellow]\n"
            f"Current version: {current}\n"
            "Check your network connection or try again later.\n"
            f"Manual install: uv tool install --force {INSTALL_URL}@<tag>"
        )
        sys.exit(1)

    cur_tuple = _parse_version(current)
    lat_tuple = _parse_version(latest)

    if check:
        if cur_tuple == lat_tuple:
            console.print(f"[green]Up-to-date:[/green] dj {current}")
        elif cur_tuple > lat_tuple:
            console.print(
                f"[dim]Local ({current}) is ahead of latest release ({latest}).[/dim]"
            )
        else:
            console.print(
                f"[yellow]Update available:[/yellow] {current} → {latest}\n"
                f"Run [bold]dj update[/bold] to install."
            )
        return

    if cur_tuple >= lat_tuple and not force:
        console.print(f"[green]Already on the latest release:[/green] dj {current}")
        return

    console.print(f"[cyan]Updating dj {current} → {latest}…[/cyan]")
    ref = f"{INSTALL_URL}@{latest}"
    result = subprocess.run(
        ["uv", "tool", "install", "--force", ref],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(
            f"[red]Update failed.[/red]\n{result.stderr.strip()}\n\n"
            f"Previous version: [bold]{current}[/bold]\n"
            f"To rollback manually: uv tool install --force {INSTALL_URL}@v{current}"
        )
        sys.exit(1)

    console.print(f"[green]Updated to {latest}.[/green]")


# ─────────────────────────────────── entry point ─────────────────────────────


def run_update(check: bool = False, force: bool = False) -> None:
    if running_from_checkout():
        _run_checkout_update(check=check)
    else:
        _run_installed_update(check=check, force=force)
