"""dj course — start/stop the offline course viewer via portless."""
from __future__ import annotations

import datetime
import os
import signal
import subprocess
import time
from pathlib import Path

from rich.console import Console

from paths import COURSE_PID_FILE, LOGS_DIR

console = Console()

_APP_DIR = Path(__file__).parent
_PID_FILE = COURSE_PID_FILE
_URL_FILE = COURSE_PID_FILE.parent / "course_url.txt"
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
    """Read the portless URL we saved on start, or fall back to the default."""
    try:
        url = _URL_FILE.read_text().strip()
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

    # portless detects vite's port by reading its stdout ("Local: http://localhost:PORT").
    # We redirect to a log file rather than DEVNULL so portless can see that line.
    log_dir = LOGS_DIR / "course"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_fh = log_path.open("w")

    proc = subprocess.Popen(
        ["npx", "portless", "course", "npm", "run", "dev"],
        cwd=_APP_DIR,
        start_new_session=True,  # new session → pid == pgid, kill group on stop
        stdout=log_fh,
        stderr=log_fh,
    )
    _PID_FILE.write_text(str(proc.pid))

    # Wait for portless to log the proxy URL line, then save it.
    time.sleep(3)
    _save_url_from_log(log_path)
    url = _get_url()
    if not _check_port_match(log_path):
        console.print(
            f"[red]Course viewer is up but vite bound to a different port than portless expects[/red] → "
            f"requests to {url} will return 502.\n"
            "[dim]Cause: vite saw a config-file change after boot, restarted, and dropped "
            f"PORT — it's now on its default 5173 instead of portless's allocated port.\n"
            f"Fix: [bold]dj course stop && dj course start[/bold] (or see {log_path}).[/dim]"
        )
        return
    console.print(f"[green]Course viewer started[/green] → {url}")
    _hint_service_install(url)
    _open(url)


def _check_port_match(log_path: Path) -> bool:
    """Return False if portless's expected port and vite's actual port disagree.

    Vite auto-restarts on config-file mtime changes and on restart binds to its
    default 5173, ignoring the PORT env var portless set — portless keeps
    proxying to the original port, so every request 502s.
    """
    import re
    try:
        text = log_path.read_text()
    except Exception:
        return True
    portless_m = re.search(r"Using port (\d+)", text)
    vite_ports = re.findall(r"localhost:(\d+)/", text)
    if not portless_m or not vite_ports:
        return True
    return portless_m.group(1) == vite_ports[-1]


def _save_url_from_log(log_path: Path) -> None:
    """Parse the portless log for '-> https://...' and write it to _URL_FILE."""
    import re
    try:
        text = log_path.read_text()
        m = re.search(r"->\s+(https://\S+)", text)
        if m:
            _URL_FILE.write_text(m.group(1).strip())
    except Exception:
        pass


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
    _URL_FILE.unlink(missing_ok=True)
    console.print("[green]Course viewer stopped.[/green]")


def _open(url: str) -> None:
    subprocess.run(["open", url], check=False)


def _hint_service_install(url: str) -> None:
    if ":1355" in url or ":443" not in url.split("localhost", 1)[-1:]:
        console.print(
            "[dim]Tip: run [bold]npx portless service install[/bold] + "
            "[bold]npx portless trust[/bold] once to get a port-free URL.[/dim]"
        )
