"""Tests for update.py — dj update logic."""
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

import update as upd


# ── _parse_version ────────────────────────────────────────────────────────────

def test_parse_version_strips_v():
    assert upd._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_no_prefix():
    assert upd._parse_version("0.1.6") == (0, 1, 6)


def test_parse_version_four_parts():
    assert upd._parse_version("1.2.3.4") == (1, 2, 3, 4)


def test_parse_version_bad_returns_zero():
    assert upd._parse_version("garbage") == (0,)


# ── checkout: dirty-tree abort ────────────────────────────────────────────────

def test_checkout_update_aborts_on_dirty_tree(monkeypatch, capsys):
    dirty_result = MagicMock()
    dirty_result.stdout = "M some_file.py\n"

    def _fake_run(cmd, **kw):
        if "status" in cmd and "--porcelain" in cmd:
            return dirty_result
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(upd, "running_from_checkout", lambda: True)
    with patch("update.subprocess.run", side_effect=_fake_run):
        with pytest.raises(SystemExit) as exc:
            upd.run_update(check=False, force=False)
    assert exc.value.code == 1


# ── checkout: detached HEAD abort ─────────────────────────────────────────────

def test_checkout_update_aborts_on_detached_head(monkeypatch):
    clean = MagicMock(stdout="", returncode=0)
    detached = MagicMock(stdout="HEAD\n", returncode=0)

    call_count = [0]
    def _fake_run(cmd, **kw):
        call_count[0] += 1
        if "--porcelain" in cmd:
            return clean
        if "--abbrev-ref" in cmd and "@{upstream}" not in " ".join(cmd):
            return detached
        return MagicMock(returncode=0, stdout="main\n")

    monkeypatch.setattr(upd, "running_from_checkout", lambda: True)
    with patch("update.subprocess.run", side_effect=_fake_run):
        with pytest.raises(SystemExit):
            upd.run_update(check=False)


# ── installed: --check reports correctly ─────────────────────────────────────

def test_installed_check_up_to_date(monkeypatch, capsys):
    monkeypatch.setattr(upd, "running_from_checkout", lambda: False)
    with patch.object(upd, "_current_version", return_value="0.1.6"), \
         patch.object(upd, "_latest_release_tag", return_value="v0.1.6"):
        upd.run_update(check=True)
    out = capsys.readouterr().out + capsys.readouterr().err
    # Should NOT exit 1.


def test_installed_check_update_available(monkeypatch, capsys):
    monkeypatch.setattr(upd, "running_from_checkout", lambda: False)
    with patch.object(upd, "_current_version", return_value="0.1.5"), \
         patch.object(upd, "_latest_release_tag", return_value="v0.1.6"):
        upd.run_update(check=True)
    # No assertion on exact message; just ensure no exception.


# ── installed: no network → clean error ──────────────────────────────────────

def test_installed_no_network_exits_cleanly(monkeypatch):
    monkeypatch.setattr(upd, "running_from_checkout", lambda: False)
    with patch.object(upd, "_current_version", return_value="0.1.6"), \
         patch.object(upd, "_latest_release_tag", return_value=None):
        with pytest.raises(SystemExit) as exc:
            upd.run_update(check=False)
    assert exc.value.code == 1


# ── installed: already latest, --force re-installs ───────────────────────────

def test_installed_force_reinstalls_even_if_current(monkeypatch):
    monkeypatch.setattr(upd, "running_from_checkout", lambda: False)
    ran = []
    with patch.object(upd, "_current_version", return_value="0.1.6"), \
         patch.object(upd, "_latest_release_tag", return_value="v0.1.6"), \
         patch("update.subprocess.run", side_effect=lambda cmd, **kw: (
             ran.append(cmd) or MagicMock(returncode=0, stderr="")
         )):
        upd.run_update(force=True)

    assert any("uv" in str(c) for c in ran), "Expected uv tool install --force to run"


# ── version compare helpers ───────────────────────────────────────────────────

def test_version_compare_newer_available():
    assert upd._parse_version("0.1.5") < upd._parse_version("v0.1.6")


def test_version_compare_already_latest():
    assert upd._parse_version("0.1.6") >= upd._parse_version("v0.1.6")


def test_version_local_ahead():
    assert upd._parse_version("0.1.7") > upd._parse_version("v0.1.6")
