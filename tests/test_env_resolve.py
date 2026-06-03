"""Tests for paths.resolve_env_file() — .env search-order logic."""
import os
from pathlib import Path

import pytest

from paths import resolve_env_file


def test_dj_env_file_env_var_takes_priority(tmp_path, monkeypatch):
    explicit = tmp_path / "custom.env"
    explicit.write_text("X=1")
    monkeypatch.setenv("DJ_ENV_FILE", str(explicit))
    assert resolve_env_file() == explicit


def test_dj_env_file_nonexistent_but_still_returned(tmp_path, monkeypatch):
    # The explicit override is returned even if the file doesn't exist yet —
    # callers decide whether to create it.
    monkeypatch.setenv("DJ_ENV_FILE", str(tmp_path / "ghost.env"))
    result = resolve_env_file()
    assert result == tmp_path / "ghost.env"


def test_cwd_dotenv_takes_second_priority(tmp_path, monkeypatch):
    monkeypatch.delenv("DJ_ENV_FILE", raising=False)
    cwd_env = tmp_path / ".env"
    cwd_env.write_text("A=1")
    monkeypatch.chdir(tmp_path)
    assert resolve_env_file() == Path(".env")


def test_dj_dir_dotenv_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DJ_ENV_FILE", raising=False)
    # No ./.env in cwd; patch DJ_DIR to tmp_path.
    import paths
    monkeypatch.setattr(paths, "DJ_DIR", tmp_path)
    dj_env = tmp_path / ".env"
    dj_env.write_text("B=1")
    monkeypatch.chdir(tmp_path.parent)  # ensure ./.env doesn't exist in cwd
    result = resolve_env_file()
    assert result == dj_env


def test_none_when_no_env_file_found(tmp_path, monkeypatch):
    monkeypatch.delenv("DJ_ENV_FILE", raising=False)
    import paths
    monkeypatch.setattr(paths, "DJ_DIR", tmp_path / "no_such")
    # Ensure cwd has no .env
    monkeypatch.chdir(tmp_path)
    result = resolve_env_file()
    assert result is None


# ── Beatport regression: read + write use same path ──────────────────────────

def test_beatport_set_env_key_uses_resolve_env_file(tmp_path, monkeypatch):
    """_set_env_key must call resolve_env_file(), not a hardcoded __file__ path."""
    env_file = tmp_path / ".env"
    env_file.write_text('BEATPORT_ACCESS_TOKEN="old"\n')
    monkeypatch.setenv("DJ_ENV_FILE", str(env_file))

    import connections.beatport as bp
    bp._set_env_key("BEATPORT_ACCESS_TOKEN", "new_value")

    content = env_file.read_text()
    assert "new_value" in content
