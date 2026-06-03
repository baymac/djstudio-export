"""Context-aware asset and app directory resolution.

Two modes:
  - checkout  (running_from_checkout() is True):  paths are resolved relative
    to the repo root via Path(__file__), identical to the old __file__
    computations they replace (regression safe).
  - installed (running_from_checkout() is False): data files are located via
    importlib.resources; app dirs come from the installed package path.

Public API
----------
running_from_checkout()     bool   — is this a source-tree run?
resolve_data_file(path)     Path   — find a shipped read-only file on disk
locate_app_dir(name)        Path   — cheap lookup; no copies, no npm
ensure_app_runnable(name)   Path   — for `start` commands; checkout→dev, installed→dist
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


# ─────────────────────────────────────────── detection ───────────────────────


@lru_cache(maxsize=None)
def running_from_checkout() -> bool:
    """True iff the tool is running from the development checkout.

    Detected by the presence of both ``pyproject.toml`` and ``.git`` next to
    this file.  A wheel never ships either.  Result is cached.
    """
    here = Path(__file__).resolve().parent
    return (here / "pyproject.toml").exists() and (here / ".git").exists()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


# ─────────────────────────────────────────── validation ──────────────────────


def _check_no_traversal(path_str: str, label: str) -> None:
    """Raise ValueError if path_str contains '..' components."""
    for part in Path(path_str).parts:
        if part == "..":
            raise ValueError(
                f"{label}: path traversal not allowed in {path_str!r}"
            )


# ─────────────────────────────────────────── data files ──────────────────────


def resolve_data_file(relative_path: str) -> Path:
    """Return the absolute Path to a shipped read-only data file.

    In checkout:  ``repo_root / relative_path`` — the same path the old
    ``Path(__file__).resolve().parent[.parent] / ...`` expressions produced.
    REGRESSION INVARIANT: checkout result == old __file__-based path.

    In installed: the file is located via ``importlib.resources`` and
    extracted once to ``~/Music/dj/cache/assets/`` if necessary (needed when
    an external tool like swiftc or node must read a real filesystem path).

    Args:
        relative_path: forward-slash path relative to the repo root, e.g.
            ``"connections/bridge/musickit_bridge.swift"``
            ``"enrich/dj_studio_sdk.js"``
    """
    _check_no_traversal(relative_path, "resolve_data_file")

    if running_from_checkout():
        return _repo_root() / relative_path

    # Installed path — extract from package data to a stable cache location.
    import importlib.resources

    from paths import CACHE_DIR

    cached = CACHE_DIR / "assets" / relative_path
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        parts = Path(relative_path).parts
        package = ".".join(parts[:-1])
        resource = parts[-1]
        data = (importlib.resources.files(package) / resource).read_bytes()
        cached.write_bytes(data)
    return cached


# ─────────────────────────────────────────── app dirs ────────────────────────


def locate_app_dir(name: str) -> Path:
    """Return the Path to a named app / package directory.

    CHEAP read-only lookup — does NOT copy files, run npm, or install anything.
    Safe to call at parse time for ``--help``, listings, or ``--version``.

    In checkout:  ``repo_root / name``.
    In installed: the installed Python package directory via
    ``importlib.resources``.

    Args:
        name: Repo-root-relative path with forward slashes, e.g.
            ``"vj"``          → the vj/ package dir
            ``"apps"``        → the apps/ package dir
            ``"apps/course"`` → the apps/course sub-package dir
    """
    _check_no_traversal(name, "locate_app_dir")

    if running_from_checkout():
        return _repo_root() / name

    import importlib.resources

    package = name.replace("/", ".")
    ref = importlib.resources.files(package)
    # For regular installed packages, files() returns a pathlib.Path directly.
    # Convert via str to handle Traversable objects that aren't Path subclasses.
    return Path(str(ref))


def ensure_app_runnable(name: str) -> Path:
    """Return the directory to pass to the app launcher.

    In checkout:  the source directory (caller runs ``npm run dev`` via
    portless, as before).
    In installed: the directory containing the pre-built static ``dist/``.
    Raises ``RuntimeError`` if the installed dist is missing.

    Args:
        name: Same format as ``locate_app_dir``, e.g. ``"apps/course"`` or
            ``"vj/cats"``.
    """
    app_dir = locate_app_dir(name)

    if running_from_checkout():
        return app_dir

    dist = app_dir / "dist"
    if not dist.is_dir():
        raise RuntimeError(
            f"Static build for '{name}' not found at {dist}.\n"
            "Re-install from a tagged release:\n"
            "  uv tool install --force git+https://github.com/baymac/dj.git@<tag>"
        )
    return app_dir
