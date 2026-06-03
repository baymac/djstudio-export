"""Tests for assets.py — context-aware asset resolution."""
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

import assets


# ── running_from_checkout ─────────────────────────────────────────────────────

def test_running_from_checkout_true_in_source_tree():
    # In the test suite we ARE in the checkout.
    assert assets.running_from_checkout() is True


def test_running_from_checkout_cached():
    assets.running_from_checkout.cache_clear()
    a = assets.running_from_checkout()
    b = assets.running_from_checkout()
    assert a is b  # same object (cached result)


def test_running_from_checkout_false_when_no_markers(tmp_path, monkeypatch):
    assets.running_from_checkout.cache_clear()
    # Patch __file__ to a path with no pyproject.toml or .git.
    monkeypatch.setattr(assets, "__file__", str(tmp_path / "assets.py"))
    assert assets.running_from_checkout() is False
    assets.running_from_checkout.cache_clear()


# ── resolve_data_file ─────────────────────────────────────────────────────────

def test_resolve_data_file_checkout_returns_repo_path():
    p = assets.resolve_data_file("connections/bridge/musickit_bridge.swift")
    assert p.is_absolute()
    # Regression: must equal what the old __file__ computation produced.
    repo_root = Path(assets.__file__).resolve().parent
    expected = repo_root / "connections/bridge/musickit_bridge.swift"
    assert p == expected


def test_resolve_data_file_checkout_js_helper():
    p = assets.resolve_data_file("enrich/dj_studio_sdk.js")
    assert p.name == "dj_studio_sdk.js"
    assert p.is_file()


def test_resolve_data_file_rejects_traversal():
    with pytest.raises(ValueError, match="traversal"):
        assets.resolve_data_file("../secrets/.env")

    with pytest.raises(ValueError, match="traversal"):
        assets.resolve_data_file("enrich/../../.env")


# ── locate_app_dir ────────────────────────────────────────────────────────────

def test_locate_app_dir_checkout_vj():
    p = assets.locate_app_dir("vj")
    assert p.is_dir()
    repo_root = Path(assets.__file__).resolve().parent
    assert p == repo_root / "vj"


def test_locate_app_dir_checkout_apps_course():
    p = assets.locate_app_dir("apps/course")
    assert p.is_dir()
    repo_root = Path(assets.__file__).resolve().parent
    assert p == repo_root / "apps/course"


def test_locate_app_dir_checkout_apps():
    p = assets.locate_app_dir("apps")
    assert p.is_dir()


def test_locate_app_dir_rejects_traversal():
    with pytest.raises(ValueError, match="traversal"):
        assets.locate_app_dir("../etc")


def test_locate_app_dir_never_writes(tmp_path, monkeypatch):
    """locate_app_dir must not create or modify any files."""
    # Track filesystem writes by patching Path.write_text / write_bytes / mkdir.
    writes = []
    real_mkdir = Path.mkdir
    real_write_bytes = Path.write_bytes

    def _mock_mkdir(self, *a, **kw):
        writes.append(("mkdir", str(self)))
        return real_mkdir(self, *a, **kw)

    def _mock_write_bytes(self, data):
        writes.append(("write_bytes", str(self)))
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "mkdir", _mock_mkdir)
    monkeypatch.setattr(Path, "write_bytes", _mock_write_bytes)

    assets.locate_app_dir("vj")
    assert writes == [], f"locate_app_dir wrote to filesystem: {writes}"


# ── ensure_app_runnable ────────────────────────────────────────────────────────

def test_ensure_app_runnable_checkout_returns_source_dir():
    p = assets.ensure_app_runnable("apps/course")
    repo_root = Path(assets.__file__).resolve().parent
    assert p == repo_root / "apps/course"


def test_ensure_app_runnable_installed_raises_if_no_dist(tmp_path):
    assets.running_from_checkout.cache_clear()
    try:
        with patch.object(assets, "running_from_checkout", return_value=False), \
             patch.object(assets, "locate_app_dir", return_value=tmp_path / "fake_app"):
            (tmp_path / "fake_app").mkdir()
            with pytest.raises(RuntimeError, match="dist"):
                assets.ensure_app_runnable("apps/course")
    finally:
        assets.running_from_checkout.cache_clear()


def test_ensure_app_runnable_installed_ok_with_dist(tmp_path):
    assets.running_from_checkout.cache_clear()
    try:
        fake_app = tmp_path / "fake_app"
        fake_app.mkdir()
        (fake_app / "dist").mkdir()
        with patch.object(assets, "running_from_checkout", return_value=False), \
             patch.object(assets, "locate_app_dir", return_value=fake_app):
            result = assets.ensure_app_runnable("apps/course")
            assert result == fake_app
    finally:
        assets.running_from_checkout.cache_clear()
