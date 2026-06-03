"""Tests for version resolution — checkout (VERSION file) vs installed (importlib.metadata)."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_version_string_reads_version_file():
    """In checkout, _version_string() should read the VERSION file."""
    import dj_cli
    ver = dj_cli._version_string()
    expected = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
    assert ver == expected


def test_version_string_prefers_importlib_metadata(monkeypatch):
    """_version_string() should prefer importlib.metadata when available."""
    import dj_cli
    import importlib.metadata as _im

    monkeypatch.setattr(_im, "version", lambda name: "9.9.9" if name == "dj" else "0.0.0")
    # Clear any lru_cache on _version_string if it has one.
    ver = dj_cli._version_string()
    assert ver == "9.9.9"


def test_dj_version_subcommand_exits_zero():
    result = subprocess.run(
        [sys.executable, "dj_cli.py", "version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "dj" in result.stdout


def test_dj_version_flag_exits_zero():
    result = subprocess.run(
        [sys.executable, "dj_cli.py", "--version"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
