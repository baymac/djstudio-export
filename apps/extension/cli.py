"""dj extension pack <name> — zip a Chrome extension under apps/<name>-extension/.

Discovers the extension source at `apps/<name>-extension/extension/` (or
`apps/<name>/extension/` as a fallback) and produces a deterministic zip at
`~/Music/dj/extensions/<name>-extension-v<version>.zip`. The version is read
from the manifest. Suitable for Chrome Web Store upload, sharing, and as the
folder source for chrome://extensions → "Load unpacked" (extract first) or
"Pack extension" (point at extracted folder + optional .pem to produce a
signed .crx).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from rich.console import Console

from paths import DJ_DIR

console = Console()

_APPS_ROOT = Path(__file__).parent.parent
_OUT_DIR = DJ_DIR / "extensions"


def _resolve_source(name: str) -> Path:
    """Find the extension/ source folder for `name`. Raises SystemExit on miss."""
    candidates = [
        _APPS_ROOT / f"{name}-extension" / "extension",
        _APPS_ROOT / name / "extension",
        _APPS_ROOT / f"{name}-extension",
        _APPS_ROOT / name,
    ]
    for c in candidates:
        if (c / "manifest.json").is_file():
            return c

    available = sorted(list_extensions())
    msg = f"[red]No extension found for[/red] {name!r}"
    if available:
        msg += f"\n  Available: {', '.join(available)}"
    else:
        msg += "\n  (no apps/*-extension/extension/manifest.json found)"
    console.print(msg)
    raise SystemExit(2)


def list_extensions() -> list[str]:
    """Return short names of every apps/<name>-extension/extension/ with a manifest."""
    if not _APPS_ROOT.exists():
        return []
    names: list[str] = []
    for child in sorted(_APPS_ROOT.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if not (child / "extension" / "manifest.json").is_file():
            continue
        short = child.name[: -len("-extension")] if child.name.endswith("-extension") else child.name
        names.append(short)
    return names


def _manifest_version(src: Path) -> str:
    try:
        data = json.loads((src / "manifest.json").read_text())
        v = data.get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:
        pass
    return "0.0.0"


# Files Chrome rejects + repo noise we never want in the zip. Keep this narrow
# so we don't silently drop something the manifest references.
_EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
_EXCLUDE_DIRS = {"__MACOSX", "node_modules", ".git"}


def _should_skip(p: Path) -> bool:
    if p.name in _EXCLUDE_NAMES or p.name.startswith("._"):
        return True
    return any(part in _EXCLUDE_DIRS for part in p.parts)


def pack(name: str) -> Path:
    """Zip the extension folder for `name` to ~/Music/dj/extensions/. Returns the path."""
    src = _resolve_source(name)
    version = _manifest_version(src)
    short = name[: -len("-extension")] if name.endswith("-extension") else name

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"{short}-extension-v{version}.zip"

    files: list[Path] = []
    for p in sorted(src.rglob("*")):
        if p.is_file() and not _should_skip(p.relative_to(src)):
            files.append(p)

    if not files:
        console.print(f"[red]No files to pack[/red] in {src}")
        raise SystemExit(2)

    # Deterministic timestamp so reruns produce byte-identical archives unless
    # source changed. zipfile clamps to 1980-01-01 as a sentinel epoch.
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            arc = p.relative_to(src).as_posix()
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, p.read_bytes())

    size_kb = out.stat().st_size / 1024
    console.print(
        f"[green]Packed[/green] {short} v{version} → {out}  "
        f"[dim]({len(files)} files, {size_kb:.1f} KB)[/dim]"
    )
    console.print(
        "[dim]Load in Chrome: chrome://extensions → Developer mode → "
        "drag the .zip in, or extract and 'Load unpacked'.[/dim]"
    )
    return out
