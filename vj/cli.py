"""dj vj <name> start/stop — start/stop a VJ visualizer under vj/<name>/ via portless.

Auto-discovers any vj/<name>/ subdirectory that contains a package.json with a
`dev` script. PID + URL files live in ~/Music/dj/state/vj_<name>.{pid,url.txt}
so multiple VJ apps can run in parallel without colliding.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from rich.console import Console

from paths import LOGS_DIR, STATE_DIR

console = Console()

_VJ_ROOT = Path(__file__).parent


def _state_files(name: str) -> tuple[Path, Path]:
    return (STATE_DIR / f"vj_{name}.pid", STATE_DIR / f"vj_{name}_url.txt")


def _fallback_url(name: str) -> str:
    return f"https://{name}.localhost"


def list_apps() -> list[str]:
    """Return sorted names of every vj/<name>/ with a package.json + dev script."""
    if not _VJ_ROOT.exists():
        return []
    apps = []
    for child in sorted(_VJ_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        pkg = child / "package.json"
        if not pkg.exists():
            continue
        try:
            data = json.loads(pkg.read_text())
        except Exception:
            continue
        if isinstance(data.get("scripts"), dict) and "dev" in data["scripts"]:
            apps.append(child.name)
    return apps


def _app_dir(name: str) -> Path:
    d = _VJ_ROOT / name
    if not d.exists() or not (d / "package.json").exists():
        available = list_apps()
        msg = f"[red]Unknown VJ app:[/red] {name}"
        if available:
            msg += f"\n  Available: {', '.join(available)}"
        else:
            msg += "\n  (no vj/<name>/ directories with a package.json found)"
        console.print(msg)
        raise SystemExit(2)
    return d


def _ensure_deps(app_dir: Path) -> None:
    if not (app_dir / "node_modules").exists():
        console.print(f"[dim]Installing npm dependencies in {app_dir.name}…[/dim]")
        subprocess.run(["npm", "install"], cwd=app_dir, check=True)


def _ensure_proxy(app_dir: Path) -> None:
    """Start the portless HTTPS proxy daemon (no-op if already running)."""
    subprocess.run(
        ["npx", "--yes", "portless", "proxy", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=app_dir,
    )


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text().strip())
    except Exception:
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_url(url_file: Path, name: str) -> str:
    try:
        url = url_file.read_text().strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return _fallback_url(name)


def _save_url_from_log(log_path: Path, url_file: Path) -> None:
    try:
        text = log_path.read_text()
        m = re.search(r"->\s+(https://\S+)", text)
        if m:
            url_file.write_text(m.group(1).strip())
    except Exception:
        pass


def _hint_service_install(url: str) -> None:
    if ":1355" in url:
        console.print(
            "[dim]Tip: run [bold]npx portless service install[/bold] + "
            "[bold]npx portless trust[/bold] once to get a port-free URL.[/dim]"
        )


def _open(url: str) -> None:
    subprocess.run(["open", url], check=False)


def run_start(name: str) -> None:
    app_dir = _app_dir(name)
    pid_file, url_file = _state_files(name)

    pid = _read_pid(pid_file)
    if pid and _is_alive(pid):
        url = _get_url(url_file, name)
        console.print(f"[green]{name} already running[/green] → {url}")
        _open(url)
        return

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    _ensure_deps(app_dir)
    _ensure_proxy(app_dir)

    # portless detects vite's port by reading its stdout ("Local: http://localhost:PORT").
    # We redirect to a log file rather than DEVNULL so portless can see that line.
    log_dir = LOGS_DIR / f"vj-{name}"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_fh = log_path.open("w")

    proc = subprocess.Popen(
        ["npx", "portless", name, "npm", "run", "dev"],
        cwd=app_dir,
        start_new_session=True,
        stdout=log_fh,
        stderr=log_fh,
    )
    pid_file.write_text(str(proc.pid))

    time.sleep(3)
    _save_url_from_log(log_path, url_file)
    url = _get_url(url_file, name)
    console.print(f"[green]{name} started[/green] → {url}")
    _hint_service_install(url)
    _open(url)


def run_stop(name: str) -> None:
    pid_file, url_file = _state_files(name)
    pid = _read_pid(pid_file)
    if not pid:
        console.print(f"[yellow]{name} is not running.[/yellow]")
        return
    if not _is_alive(pid):
        pid_file.unlink(missing_ok=True)
        console.print(f"[yellow]{name} was not running (stale PID cleared).[/yellow]")
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    pid_file.unlink(missing_ok=True)
    url_file.unlink(missing_ok=True)
    console.print(f"[green]{name} stopped.[/green]")
