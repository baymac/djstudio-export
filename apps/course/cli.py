"""dj course — start/stop the offline course viewer via portless."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from rich.console import Console

from paths import COURSE_PID_FILE

console = Console()

_APP_DIR = Path(__file__).parent
_PID_FILE = COURSE_PID_FILE
_FALLBACK_URL = "https://course.localhost"


def _ensure_deps() -> None:
    if not (_APP_DIR / "node_modules").exists():
        console.print("[dim]Installing npm dependencies…[/dim]")
        subprocess.run(["npm", "install"], cwd=_APP_DIR, check=True)


def _ensure_proxy() -> None:
    """Start the portless HTTPS proxy daemon (no-op if already running)."""
    subprocess.run(
        ["npx", "--yes", "portless", "proxy", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=_APP_DIR,
    )


def _read_pid() -> int | None:
    try:
        return int(_PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_url() -> str:
    """Ask portless for the current URL of the 'course' app."""
    try:
        result = subprocess.run(
            ["npx", "portless", "get", "course"],
            cwd=_APP_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        url = result.stdout.strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return _FALLBACK_URL


def run_start() -> None:
    pid = _read_pid()
    if pid and _is_alive(pid):
        url = _get_url()
        console.print(f"[green]Course viewer already running[/green] → {url}")
        _open(url)
        return

    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ensure_deps()
    _ensure_proxy()

    # portless wraps vite, detects its port, and proxies https://course.localhost to it.
    proc = subprocess.Popen(
        ["npx", "portless", "course", "npm", "run", "dev"],
        cwd=_APP_DIR,
        start_new_session=True,  # new session → pid == pgid, kill group on stop
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _PID_FILE.write_text(str(proc.pid))

    time.sleep(3)
    url = _get_url()
    console.print(f"[green]Course viewer started[/green] → {url}")
    _hint_service_install(url)
    _open(url)


def run_stop() -> None:
    pid = _read_pid()
    if not pid:
        console.print("[yellow]Course viewer is not running.[/yellow]")
        return
    if not _is_alive(pid):
        _PID_FILE.unlink(missing_ok=True)
        console.print("[yellow]Course viewer was not running (stale PID cleared).[/yellow]")
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _PID_FILE.unlink(missing_ok=True)
    console.print("[green]Course viewer stopped.[/green]")


def _open(url: str) -> None:
    subprocess.run(["open", url], check=False)


def _hint_service_install(url: str) -> None:
    if ":1355" in url or ":443" not in url.split("localhost", 1)[-1:]:
        console.print(
            "[dim]Tip: run [bold]npx portless service install[/bold] + "
            "[bold]npx portless trust[/bold] once to get a port-free URL.[/dim]"
        )
