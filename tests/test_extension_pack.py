"""Tests for apps/extension/cli.py — the `dj extension pack` Chrome packer.

Builds a fake apps/ tree and DJ_DIR under tmp_path via monkeypatch, then asserts
the zip is produced at the right path, excludes noise, and is deterministic.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from apps.extension import cli as ext


def _make_extension(apps_root, name, *, version="1.2.3", nested="extension"):
    """Create apps_root/<name>-extension/<nested>/ with a manifest + a file."""
    src = apps_root / f"{name}-extension"
    if nested:
        src = src / nested
    src.mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps({"name": name, "version": version}))
    (src / "background.js").write_text("// bg\n")
    (src / "icons").mkdir()
    (src / "icons" / "icon16.png").write_bytes(b"\x89PNG\r\n")
    return src


@pytest.fixture
def fake_apps(tmp_path, monkeypatch):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    out_dir = tmp_path / "dj" / "extensions"
    monkeypatch.setattr(ext, "_APPS_ROOT", apps_root)
    monkeypatch.setattr(ext, "_OUT_DIR", out_dir)
    return apps_root, out_dir


def test_pack_writes_zip_with_manifest_at_root(fake_apps):
    apps_root, out_dir = fake_apps
    _make_extension(apps_root, "1001T", version="1.0.0")

    out = ext.pack("1001T")

    assert out == out_dir / "1001T-extension-v1.0.0.zip"
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    # manifest sits at the archive root (no nested extension/ folder)
    assert "manifest.json" in names
    assert "background.js" in names
    assert "icons/icon16.png" in names


def test_version_comes_from_manifest(fake_apps):
    apps_root, out_dir = fake_apps
    _make_extension(apps_root, "foo", version="9.9.9")
    out = ext.pack("foo")
    assert out.name == "foo-extension-v9.9.9.zip"


def test_excludes_ds_store_and_node_modules(fake_apps):
    apps_root, out_dir = fake_apps
    src = _make_extension(apps_root, "bar")
    (src / ".DS_Store").write_text("junk")
    (src / "._sidecar").write_text("junk")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "dep.js").write_text("// dep")

    out = ext.pack("bar")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert ".DS_Store" not in names
    assert "._sidecar" not in names
    assert not any(n.startswith("node_modules/") for n in names)


def test_deterministic_across_runs(fake_apps):
    apps_root, out_dir = fake_apps
    _make_extension(apps_root, "det")
    first = ext.pack("det").read_bytes()
    second = ext.pack("det").read_bytes()
    assert first == second  # fixed 1980 timestamps → byte-identical


def test_resolves_bare_extension_dir_fallback(fake_apps):
    # apps/<name>/extension/ (no -extension suffix on the parent)
    apps_root, out_dir = fake_apps
    src = apps_root / "baz" / "extension"
    src.mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps({"version": "2.0.0"}))
    (src / "x.js").write_text("// x")

    out = ext.pack("baz")
    assert out.name == "baz-extension-v2.0.0.zip"


def test_unknown_name_raises(fake_apps):
    with pytest.raises(SystemExit):
        ext.pack("does-not-exist")


def test_list_extensions_finds_named_extensions(fake_apps):
    apps_root, out_dir = fake_apps
    _make_extension(apps_root, "alpha")
    _make_extension(apps_root, "beta")
    assert ext.list_extensions() == ["alpha", "beta"]


def test_manifest_without_version_defaults(fake_apps):
    apps_root, out_dir = fake_apps
    src = apps_root / "nover-extension" / "extension"
    src.mkdir(parents=True)
    (src / "manifest.json").write_text("{}")
    (src / "a.js").write_text("// a")
    out = ext.pack("nover")
    assert out.name == "nover-extension-v0.0.0.zip"
